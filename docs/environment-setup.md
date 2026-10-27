# 建模环境使用说明

本项目使用独立的 `mc-base` 环境。Python、建模、气象与 GIS 依赖统一由 conda-forge 安装。
跨机器复现的完整步骤见[项目README](../README.md)，所有命令均在自己的项目根目录执行，不绑定安装盘符或用户名。

## 日常使用

在项目根目录打开 **Miniforge Prompt** 或已初始化conda的终端，运行：

```bat
conda activate mc-base
python scripts\check_environment.py
```

命令行最前面出现 `(mc-base)` 即表示已激活；运行 `python --version`
应显示 Python 3.12。每次新开终端后都需要激活，退出时运行
`conda deactivate`。已有的 VS Code 终端如仍使用其他环境，重新打开终端
或通过“Python: Select Interpreter”选择 `mc-base`。

启动 Notebook 工作界面：

```bat
jupyter lab
```

Windows 下应先激活环境再运行脚本，以加载数值计算 DLL 及 GDAL/PROJ
数据路径。不要用系统 Python 运行项目。也可不激活，改用以下显式命令：

```bat
conda run -n mc-base --no-capture-output python scripts/check_environment.py
```

VS Code 应打开整个项目文件夹，在“Python: Select Interpreter”中选择自己创建的`mc-base`环境。
如需注册Notebook内核，在激活后运行`python -m ipykernel install --user --name mc-base --display-name "Python (MathorCup mc-base)"`，
再选择该内核。工作区不固定Python或conda的安装目录。

## 已选能力

| 用途 | 主要库 |
| --- | --- |
| 数据、统计与基线建模 | NumPy、Pandas、SciPy、scikit-learn、statsmodels |
| 图表与表格文件 | Matplotlib、Seaborn、openpyxl、PyArrow |
| 气象与多维数据 | Xarray、netCDF4、h5netcdf、Dask、Bottleneck |
| 地理空间与遥感栅格 | GeoPandas、Rasterio、Rioxarray、PyProj、Shapely、Cartopy |
| 交互工作与配置 | JupyterLab、ipykernel、PyYAML |

QGIS 使用其自带的 Python、GDAL 和 PROJ，通过独立安装程序维护。
项目脚本使用 `mc-base` 中的对应依赖；避免把 QGIS 的 DLL 或 Python
目录全局加入项目环境。地图制图和地形检查可在 QGIS 中进行。

## 验证与复现

`scripts/check_environment.py` 使用固定种子的合成数据，验证模型拟合、
Excel/Parquet、NetCDF、Dask 聚合、GeoPackage、空间连接、GeoTIFF、
坐标转换和地图绘制。生成文件位于 `output/environment-check/`；其中的
数值和地图仅用于工具检查，不能作为比赛研究结果。

环境文件分为：

- `environment.yml`：直接依赖清单，适合维护和跨机器重新求解。
- `environment.win-64.yml`：安装后的版本清单，记录全部依赖版本。
- `environment.win-64.lock.txt`：Windows 64 位显式锁定文件，记录具体构建及校验值。

锁定文件采用 SHA-256 校验值；`mc-base` 自身配置了严格的 conda-forge
频道优先级。

在 Miniforge Prompt 中精确重建已验证环境：

```bat
conda create -n mc-base-reproduced --file environment.win-64.lock.txt
```

锁定文件适用于 Windows 64 位；其他平台应使用 `environment.yml` 重新求解并验证。

## 论文编译

VS Code 项目设置提供
**XeLaTeX + bibliography (latexmk)** 编译方案，支持中文与 Biber 参考文献。
TeX发行版自行安装，`latexmk`从PATH发现，不要求固定版本目录或盘符。
编译生成文件保存在 `.tex` 所在文件夹的 `build/` 下。

## 后续约定

原始数据保留在 `data/`，不直接覆盖；建模时分别保存数据字典、来源、
时间与空间基准、数据划分、随机种子、超参数及关键中间结果。
Git 默认忽略原始数据与生成文件，应另外备份这些文件。
PyTorch、YOLO 和 Origin 当前暂缓配置，后续根据具体任务决定是否补充。

## 本次安装修复记录

以下是早期环境准备的历史记录，不是其他电脑复现必须执行的步骤。

本机 Miniforge 26.9.4 安装的 `conda-launchers` 文件存在，但安装记录的
`paths_data` 为空，导致创建含 Windows 命令入口的环境失败。
已从原安装包缓存重装该组件，恢复六个启动器的校验记录；随后离线
创建 `mc-base` 成功。保留现有 Miniforge，无需重新安装。
