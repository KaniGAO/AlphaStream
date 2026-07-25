# -*- coding: utf-8 -*-
"""
AlphaStream - 数据落盘与读取工具 (Data I/O Utilities)
================================================================

【这个模块解决什么问题？】
    AlphaStream 的所有结构化数据都用 Parquet 落盘（而不是 CSV）：
      - Data/Raw/       ：原始行情（如 hk_market_raw.parquet，约 44 万行）
      - Data/Processed/ ：因子收益、特异 alpha、因子暴露矩阵等
    为什么统一用 Parquet（列式存储）而非 CSV？
      * 体积通常小 5~10 倍：同列同类型 → 压缩率高（snappy/zstd）
      * 只读需要的列极快：列裁剪 column pruning，不用扫整张表
      * 自带 schema：int/float/date/category 类型原样保留，读回不用再 cast
    原始行情通常是 CSV（交易所/数据商导出），本模块提供统一、可复用的
    「清洗 -> 落盘」与「读取」入口，避免在 notebook / Src 里散落重复的
    to_parquet 代码。

【公开 API（四个函数）】
    csv_to_parquet()   : 单个 CSV -> （可选清洗）-> 落盘 Parquet（Raw 层入口）
    save_parquet()     : 任意 DataFrame -> 落盘 Parquet（通用，含参数/边界校验）
    load_parquet()     : Parquet -> DataFrame（支持只读指定列，省 IO）
    convert_csv_dir()  : 批量把目录下所有 CSV 转成 Parquet

【依赖】
    pip install pandas pyarrow
    （pyarrow 是 to_parquet / read_parquet 的默认引擎，必须安装）

【路径约定】
    模块默认用「当前文件位置」反推项目根，从而定位 Data 目录：
        Src/data_io.py -> 父目录 = 项目根 -> /Data/Raw、/Data/Processed
    函数也都接受任意绝对/相对路径，调用方也可自行指定。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# 日志：用模块级 logger，方便在 notebook / 服务里统一接管输出
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
# 若调用方没配置 handler，给一个最基础的 stderr 输出，避免处理过程静默失败
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


# ===========================================================================
# 0. 内部小工具：定位项目目录 + 路径解析
# ===========================================================================
def _project_root() -> Path:
    """返回 AlphaStream 项目根目录（含 Data/、Src/、Notebooks/ 的那一层）。

    实现：取本文件 data_io.py 所在目录（Src/）的上一级。
    这样无论从哪调用，都能稳定找到 Data/，不依赖当前工作目录 cwd。
    """
    return Path(__file__).resolve().parent.parent


def _resolve_path(path) -> Path:
    """把传入的路径统一解析成绝对 Path。

    - 字符串或 Path 都接受
    - 相对路径以「当前工作目录」为基准展开
    - 已存在 / 不存在都返回 Path 对象；是否创建由调用方决定
    """
    return Path(path).resolve()


# ===========================================================================
# 1. csv_to_parquet —— 原始 CSV -> 清洗 -> 落盘 Parquet（Raw 层入口）
# ===========================================================================
def csv_to_parquet(
    csv_path,
    parquet_path,
    *,
    parse_dates=None,
    numeric_cols=None,
    winsorize_quantile=None,
    keep_cols=None,
    compression="snappy",
    overwrite=False,
):
    """把一个 CSV 文件读取、可选清洗后，落盘为 Parquet。

    这是「原始数据进系统」的标准入口：交易所/数据商导出的 CSV 通常
    带脏数据（类型全是字符串、日期是字符串、含极端值），本函数一次性
    把它变成干净、压缩、带类型的 Parquet，供后续因子计算直接消费。

    参数
    ----
    csv_path : str | Path
        输入 CSV 路径。文件必须存在，否则抛 FileNotFoundError。
    parquet_path : str | Path
        输出 Parquet 路径。父目录不存在会自动创建（mkdir -p 语义）。
    parse_dates : list[str] | None, 默认 None
        需要解析成 datetime 的列名列表（如 ["date", "trade_date"]）。
        Parquet 能原生存 timestamp，比 CSV 的纯字符串省空间且好用。
    numeric_cols : list[str] | None, 默认 None
        需要强制转成数值 (float64) 的列。缺失值会被填成 NaN（pandas 默认）。
        不传则 pandas 自动推断；传了可避免 "1,234" 这类带逗号的字符串
        被误判成 object 类型导致后续数值运算报错。
    winsorize_quantile : float | None, 默认 None
        全样本去极值的分位阈值（如 0.025 表示截掉上下各 2.5%）。
        仅对数值列生效，把超出分位的点压到边界（clip），不改变分布形状。
        作用：消除异常值对因子标准化、协方差估计的污染。
        AlphaStream 的因子构建就用了 2.5%/97.5% 去极值（见 README）。
        注意：这里做的是「全样本」初洗，仅适合原始数据入库前；
              因子层面的「横截面」去极值请放在因子构建阶段做。
    keep_cols : list[str] | None, 默认 None
        只保留这些列；None 表示保留全部。用于丢弃 CSV 里的无用列。
    compression : str, 默认 "snappy"
        Parquet 压缩算法。snappy 速度最快、压缩比适中；
        可选 "gzip"（更高压缩比、稍慢）、"zstd"（速度与压缩平衡）、None（不压缩）。
    overwrite : bool, 默认 False
        输出文件已存在时是否覆盖。False 则直接抛 FileExistsError，
        防止误覆盖已落盘的数据。

    返回
    ----
    Path
        实际写出的 Parquet 绝对路径（方便链式调用 / 日志）。

    异常
    ----
    FileNotFoundError : csv_path 不存在
    FileExistsError   : parquet_path 已存在且 overwrite=False
    ValueError        : winsorize_quantile 不在 (0, 0.5) 区间；或 keep_cols 含不存在的列
    """
    # --- 1. 路径校验 ---
    csv_path = _resolve_path(csv_path)
    parquet_path = _resolve_path(parquet_path)
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV 不存在: {csv_path}")
    if parquet_path.exists() and not overwrite:
        raise FileExistsError(
            f"目标 Parquet 已存在（设 overwrite=True 可覆盖）: {parquet_path}"
        )
    if winsorize_quantile is not None and not (0 < winsorize_quantile < 0.5):
        raise ValueError("winsorize_quantile 必须在 (0, 0.5) 之间")

    # --- 2. 读取 CSV（按需求解析日期 / 数值） ---
    # dtype 指定能让 pandas 跳过类型探测、直接给对类型，既快又稳。
    read_kwargs = {}
    if numeric_cols:
        read_kwargs["dtype"] = {c: "float64" for c in numeric_cols}
    df = pd.read_csv(csv_path, parse_dates=parse_dates, **read_kwargs)
    logger.info(f"读取 CSV: {csv_path} -> 形状 {df.shape}")

    # --- 3. 选列（可选） ---
    if keep_cols is not None:
        missing = [c for c in keep_cols if c not in df.columns]
        if missing:
            raise ValueError(f"keep_cols 含不存在的列: {missing}")
        df = df[keep_cols]

    # --- 4. 去极值（可选，仅数值列） ---
    if winsorize_quantile is not None:
        num_cols = df.select_dtypes(include="number").columns
        lo, hi = winsorize_quantile, 1 - winsorize_quantile
        for col in num_cols:
            # clip 到上下分位，超出部分直接压到边界，不改变分布形状
            q_low, q_high = df[col].quantile([lo, hi])
            df[col] = df[col].clip(q_low, q_high)
        logger.info(f"去极值完成（分位 {lo:.3f}~{hi:.3f}）")

    # --- 5. 落盘 Parquet（父目录自动创建） ---
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, engine="pyarrow", compression=compression)
    logger.info(
        f"已落盘 Parquet: {parquet_path}（{parquet_path.stat().st_size} bytes）"
    )
    return parquet_path


# ===========================================================================
# 2. save_parquet —— 任意 DataFrame -> 落盘 Parquet（通用入口）
# ===========================================================================
def save_parquet(
    df,
    parquet_path,
    *,
    compression="snappy",
    overwrite=False,
    partition_cols=None,
):
    """把任意 DataFrame 落盘为 Parquet（通用入口，不限于 CSV 来源）。

    项目里「Processed 层」的产物都走这里：
      - 因子收益矩阵（factor_returns.parquet）
      - 特异 alpha 残差（idiosyncratic_alpha.parquet）
      - 因子暴露矩阵 B（N x K，后续风险模型要用）

    参数
    ----
    df : pd.DataFrame
        要落盘的表。空表会直接抛 ValueError（落盘空表通常是上游 bug 信号）。
    parquet_path : str | Path
        输出路径；父目录自动创建（mkdir -p 语义）。
    compression : str, 默认 "snappy"
        压缩算法，含义同 csv_to_parquet（snappy / gzip / zstd / None）。
    overwrite : bool, 默认 False
        输出已存在时是否覆盖；False 则抛 FileExistsError 防误覆盖。
    partition_cols : list[str] | None, 默认 None
        按这些列做「分区存储」，写出成 parquet 目录而非单个文件。
        例：partition_cols=["year"] -> Data/Processed/factor/year=2024/part-0.parquet
        好处：按分区读时可直接跳过无关文件，配合 load_parquet(filters=) 谓词下推。
        注意：分区列不会同时出现在每个文件里，而是变成目录名前缀。

    返回
    ----
    Path : 实际写出的路径（单文件或分区目录根）。

    异常
    ----
    ValueError      : df 为空，或 partition_cols 含不存在的列
    FileExistsError : 输出已存在且 overwrite=False
    """
    if df is None or df.empty:
        raise ValueError("df 为空，拒绝落盘空表（通常是上游 bug）")
    parquet_path = _resolve_path(parquet_path)
    if parquet_path.exists() and not overwrite:
        raise FileExistsError(
            f"目标 Parquet 已存在（设 overwrite=True 可覆盖）: {parquet_path}"
        )
    if partition_cols is not None:
        missing = [c for c in partition_cols if c not in df.columns]
        if missing:
            raise ValueError(f"partition_cols 含不存在的列: {missing}")

    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    # partition_cols=None 时写单文件；否则写分区目录
    df.to_parquet(
        parquet_path,
        engine="pyarrow",
        compression=compression,
        partition_cols=partition_cols,
    )
    logger.info(f"已落盘 Parquet: {parquet_path}（形状 {df.shape}）")
    return parquet_path


# ===========================================================================
# 3. load_parquet —— Parquet -> DataFrame（支持列裁剪 / 分区过滤）
# ===========================================================================
def load_parquet(parquet_path, *, columns=None, filters=None):
    """从 Parquet 读回 DataFrame。

    相比直接用 pd.read_parquet 的增量：支持「只读指定列」和「按分区过滤」，
    在处理大表（如 44 万行的 hk_market_raw）时大幅省 IO。

    参数
    ----
    parquet_path : str | Path
        输入 Parquet（单文件或分区目录）。不存在抛 FileNotFoundError。
    columns : list[str] | None, 默认 None
        只读取这些列（列裁剪 column pruning）。None = 读全部。
        例：load_parquet(p, columns=["date", "close"]) 只读两列，其余不进内存。
    filters : list[tuple] | None, 默认 None
        仅对「分区目录」生效的谓词下推，格式 [("year", "=", 2024)]。
        不满足的行在读取阶段就被跳过，比读回再 filter 快得多。

    返回
    ----
    pd.DataFrame : 读回的表。
    """
    parquet_path = _resolve_path(parquet_path)
    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet 不存在: {parquet_path}")

    df = pd.read_parquet(
        parquet_path,
        engine="pyarrow",
        columns=columns,
        filters=filters,
    )
    logger.info(f"读取 Parquet: {parquet_path} -> 形状 {df.shape}")
    return df


# ===========================================================================
# 4. convert_csv_dir —— 批量把目录下所有 CSV 转成 Parquet
# ===========================================================================
def convert_csv_dir(csv_dir, parquet_dir=None, *, pattern="*.csv", **csv_kwargs):
    """批量把目录下所有 CSV 转成 Parquet。

    适合「一次性把一整包原始行情 CSV 全部落盘」的场景。
    每个 CSV 会按同名生成 <name>.parquet。

    参数
    ----
    csv_dir : str | Path
        含 CSV 的源目录。
    parquet_dir : str | Path | None, 默认 None
        输出目录；None 表示与 csv_dir 相同（原地转换）。
    pattern : str, 默认 "*.csv"
        glob 匹配模式，可用 "*.csv"、"stock_*.csv" 等。
    **csv_kwargs :
        其余关键字参数原样传给 csv_to_parquet（如 parse_dates、
        numeric_cols、winsorize_quantile、compression、overwrite）。

    返回
    ----
    list[Path] : 实际写出的 Parquet 路径列表（按文件名排序）。

    异常
    ----
    NotADirectoryError : csv_dir 不是目录或不存在
    """
    csv_dir = _resolve_path(csv_dir)
    if not csv_dir.is_dir():
        raise NotADirectoryError(f"CSV 目录不存在: {csv_dir}")
    parquet_dir = _resolve_path(parquet_dir) if parquet_dir else csv_dir
    parquet_dir.mkdir(parents=True, exist_ok=True)

    out_paths = []
    for csv_file in sorted(csv_dir.glob(pattern)):
        out = parquet_dir / (csv_file.stem + ".parquet")
        # 逐个转换；单个失败不影响其余（记录日志后继续）
        try:
            p = csv_to_parquet(csv_file, out, **csv_kwargs)
            out_paths.append(p)
        except Exception as e:  # noqa: BLE001 - 批量任务需容错，单文件失败继续
            logger.error(f"转换失败 {csv_file.name}: {e}")
    logger.info(f"批量转换完成：{len(out_paths)} 个文件 -> {parquet_dir}")
    return out_paths


# ===========================================================================
# 演示 / 自测：直接 `python Src/data_io.py` 即可看到完整 round-trip
# ===========================================================================
if __name__ == "__main__":
    import tempfile

    # 1) 造一份「港股行情」示例 CSV（字段参照 README：价格/市值/PE/成交量）
    sample = """ticker,date,close,mkt_cap,pe,volume
0001.HK,2024-01-02,68.5,2100000,18.2,1250000
0002.HK,2024-01-02,402.0,4800000,22.5,880000
0003.HK,2024-01-02,55.3,1500000,9.1,2100000
0001.HK,2024-01-03,69.1,2120000,18.4,1100000
0002.HK,2024-01-03,398.5,4750000,22.1,920000
0003.HK,2024-01-03,56.0,1520000,9.3,1980000
"""
    with tempfile.TemporaryDirectory() as tmp:
        csv_p = Path(tmp) / "hk_sample.csv"
        csv_p.write_text(sample, encoding="utf-8")
        pq_p = Path(tmp) / "hk_sample.parquet"

        # 2) CSV -> Parquet（解析日期、数值列强转、去极值）
        csv_to_parquet(
            csv_p,
            pq_p,
            parse_dates=["date"],
            numeric_cols=["close", "mkt_cap", "pe", "volume"],
            winsorize_quantile=0.025,
            overwrite=True,
        )

        # 3) 读回（只取需要的列，演示列裁剪省 IO）
        df = load_parquet(pq_p, columns=["ticker", "date", "close"])
        print("\n读回的 DataFrame：")
        print(df)
        print("\ndate 列类型（应为 datetime64）:", df["date"].dtype)
        print("close 列类型（应为 float64）:", df["close"].dtype)
        print("round-trip 行数一致:", len(df) == 6)
