# MathorCup赛道B项目

当前位于第一问的观测解释与特征探索阶段。最终灾害标签、关键降水特征和模型评价尚未定义；科学边界见[分析约束](config/analysis-constraints.yml)及[待确认清单](docs/pending-questions.md)。

## 在其他电脑复现

项目可以放在任意目录，支持目录名包含中文和空格。脚本根据自身位置寻找项目根目录，不要求原电脑的盘符、用户名或Miniforge安装位置，也不依赖当前工作目录。

### 1 准备环境

安装Miniforge或其他可使用conda的发行版。在项目根目录打开终端：

```console
conda env create -f environment.yml
conda activate mc-base
python scripts/check_environment.py
```

Windows 64位如需使用本项目已记录的精确构建版本，可替代环境创建步骤：

```console
conda create -n mc-base --file environment.win-64.lock.txt
```

激活环境后运行Python，或使用`conda run -n mc-base --no-capture-output python ...`，以正确加载GDAL、PROJ及数值库。其他系统用`environment.yml`重新求解；Windows显式锁定文件不能当作其他系统的锁定文件。

### 2 放入同版本官方输入

将8个原始ZIP/RAR原样放在`data/附件/`，不改名、不覆盖内容。具体文件名、大小及SHA-256见[输入版本清单](config/input-manifest.json)。原始数据不随Git分发，需要从官方来源取得或由项目持有者另行提供。

```text
项目根目录/
  config/
  scripts/
  tests/
  data/
    附件/
      （1）...zip
      （2）...zip
      （3）...rar
      （4）...zip 至 （8）...zip
  output/                   运行时生成
```

空间审计需要PATH上可发现、支持RAR的`bsdtar`或`tar`。程序优先找`bsdtar`；Windows系统tar已在本项目验证，其他系统的GNU tar可能不支持RAR。缺少兼容工具会明确报错。制图需要系统有可用中文字体；脚本可选微软雅黑、Noto Sans CJK、思源黑体等，数值计算不依赖字体文件的安装位置。

```console
python scripts/run_pipeline.py --check-inputs
```

### 3 运行分析

完整离线分析按顺序运行审计、报告、无标签探索、变量关系及多高度剖面：

```console
python scripts/run_pipeline.py
```

仅显示步骤而不读数据、写输出：

```console
python scripts/run_pipeline.py --dry-run
```

也可选择步骤，按列出的顺序执行；首次运行后续分析前须先完成`tabular`以生成字段字典与诊断Parquet：

```console
python scripts/run_pipeline.py --steps tabular,exploration,relations,profiles
python -m unittest discover -s tests -v
```

从项目之外的目录调用时，只需将命令中的脚本位置改为该目录到项目的相对路径；例如在项目父目录执行`python "项目目录名/scripts/run_pipeline.py" --dry-run`。运行器采用当前环境的`sys.executable`，不会另找原作者安装的Python。

### 4 元数据与来源

基础分析使用已核验并纳入版本管理的[观测覆盖窗事实摘录](config/observation-reference.json)。该文件保存官方起止标签、epoch毫秒、时区、数据集UUID及原JSON快照哈希；它不定义仪器运行期、小时支持区间或灾害时间。完整JSON缓存若存在会互校，缓存缺失也可以离线复现本轮分析。

如需重新读取官网公开详情、导出和文档列表，单独运行以下联网步骤：

```console
python scripts/fetch_official_metadata.py --refresh
```

新官方资料与冻结定义冲突时停止并审查来源版本，不自动替换参考定义或修改原始时间。新的数据版本也必须另行更新来源、哈希和分析说明。

## 结果位置

新增26项专题数据的取舍、四问首版交付与10月30日20:00截止安排，见[补充数据与支撑材料安排](docs/data-request-and-delivery.md)。当前管线仍只使用已收到并核验的原8包，尚未生成第二至四问模型或最终提交包。

| 内容 | 位置 |
| --- | --- |
| 原始附件质量审计 | `output/data_audit/` |
| 无标签观测探索 | `output/observation_exploration/` |
| 非降水变量关系 | `output/variable_relations/` |
| 同刻多高度与梯度 | `output/vertical_profiles/` |
| 各步骤日志和运行清单 | `output/reproduction/` |
| 可阅读的阶段报告 | `docs/` |

所有统计视图另存，原始包只读；QC=4是提供方插补，本项目不新增插补。日内图按已确认的北京时间小时标签描述，未确认的站点坐标或降水定义不被当作事实。

## 已做的迁移验证

本轮已在Windows同一已安装环境下，把代码、配置和原始包放入含中文及空格的新目录，未复制任何生成结果或官网缓存，从项目外启动环境检查及完整7步分析。22份数值表（CSV及CSV.gz）与原目录逐字节一致，8个原包哈希不变。该测试证明本轮分析不绑定原项目目录或元数据缓存；它不等于所有操作系统和任意依赖版本均已验证。

空间NetCDF通过已声明的h5netcdf后端读取，修复了实测中netCDF4原生路径API在中文目录报文件不存在的问题；原始数组和属性已经互校一致。环境检查仍通过内存方式验证netCDF4解码，避免将路径兼容问题误判为数据缺失。

可运行`python scripts/verify_relocation.py`复做这一检查。报告位于`output/reproduction/relocation_verification.json`，步骤日志为同目录下的`relocation.log`。

## 可选文档与编辑器

Word过程说明不是数值管线的必需步骤。可在独立Python环境安装`requirements-documents.txt`，运行`python scripts/build_project_roadmap.py`生成文档。Windows可通过`powershell -File scripts/render_project_roadmap.ps1`调用已安装的Microsoft Word导出供检查的PDF，再运行`python scripts/rasterize_project_roadmap.py`逐页栅格化。其他系统可用自身的文档渲染器，将PDF保存在`output/document_qa/project_roadmap/project-roadmap.pdf`后执行同一栅格化步骤。文档渲染后端与字体不同可能影响分页，不能跳过目视核验。

VS Code工作区不固定Git、conda、Python和TeX的安装位置。首次打开时通过“Python: Select Interpreter”选择自己的`mc-base`环境；Git与`latexmk`从PATH发现。QGIS、TeX Live、Word等为相应用途的可选工具，不是核心Python分析必须安装的依赖。Origin和PyTorch继续暂缓。
