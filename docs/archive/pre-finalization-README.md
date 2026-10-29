# MathorCup赛道B项目

完成情况统一查看[项目进度](PROGRESS.md)。第一问首版入口为[案例对照报告](docs/question1-v1.md)，第二问空间条件筛查见[第二问记录](docs/question2-v0.md)，第三问和第四问首版见[时间预警](docs/question3-v0.md)和[中心线传播情景](docs/question4-v0.md)。新增坐标、DEM、卫星范围、中心线、v1.1高程变化的元数据/限制见[新增空间资料核验](docs/new-evidence-review.md)。不确定的时间、触发标签、沉积厚度、统计95%覆盖率和模型验证均不伪装为已知结果。

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

### 2 放入同版本官方输入与可选外部资料

将8个原始ZIP/RAR原样放在`data/附件/`，不改名、不覆盖内容。具体文件名、大小及SHA-256见[输入版本清单](config/input-manifest.json)。原始数据不随Git分发，需要从官方来源取得或由项目持有者另行提供。

中心线与geo-pera v1.1口岸段产品是可选外部输入，放入`data/supplementary/geo-pera-v1.1/`；2019灾前DEM、灾后2 m composite、UNESCO SHP与UNOSAT GDB也需按[新增空间资料核验](docs/new-evidence-review.md)所列相对路径准备。影像衍生数据受CC BY-NC 4.0许可且体积较大，GitHub只保存复现程序、元数据和说明，不推送数据本体。只使用v1.1修正版，v1.0旧高程变化产品已撤回。

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

新增26项专题数据的取舍、四问首版交付与10月30日20:00截止安排，见[补充数据与支撑材料安排](docs/data-request-and-delivery.md)。新空间资料与Q3/Q4复算顺序如下：

```console
python scripts/prepare_event_context.py
python scripts/build_question3_baseline.py
python scripts/build_question4_kinematic.py
```

脚本需要对应数据先按说明放入`data/`。生成物在`output/event_context/`、`output/question3/`和`output/question4/`；重要结论和解释已记录于`docs/`。

| 内容 | 位置 |
| --- | --- |
| 原始附件质量审计 | `output/data_audit/` |
| 无标签观测探索 | `output/observation_exploration/` |
| 非降水变量关系 | `output/variable_relations/` |
| 同刻多高度与梯度 | `output/vertical_profiles/` |
| 各步骤日志和运行清单 | `output/reproduction/` |
| 四问报告、来源核验与数据模拟/缺口清单 | `docs/question1-v1.md`至`docs/question4-v0.md`；`docs/new-evidence-review.md`；`docs/data-provenance-and-critical-gaps.md` |
| 可阅读的阶段报告 | `docs/` |

所有统计视图另存，原始包只读；QC=4是提供方插补，本项目不新增插补。日内图按已确认的北京时间小时标签描述。赛题原文10:30与用户报告的10:52冰崩、10:54:19–10:55:10转化时段、10:59到达分别保存；不把转化阶段自动等同于精确触发。第四问速度敏感性和转化位置只是透明情景，不是实测或统计校准结果。GFS/WRF/TPCSM均按数值模式输出解释，详见数据来源清单。

## 已做的迁移验证

本轮已在Windows同一已安装环境下，把代码、配置和原始包放入含中文及空格的新目录，未复制任何生成结果或官网缓存，从项目外启动环境检查及完整7步分析。22份数值表（CSV及CSV.gz）与原目录逐字节一致，8个原包哈希不变。该测试证明本轮分析不绑定原项目目录或元数据缓存；它不等于所有操作系统和任意依赖版本均已验证。

空间NetCDF通过已声明的h5netcdf后端读取，修复了实测中netCDF4原生路径API在中文目录报文件不存在的问题；原始数组和属性已经互校一致。环境检查仍通过内存方式验证netCDF4解码，避免将路径兼容问题误判为数据缺失。

可运行`python scripts/verify_relocation.py`复做这一检查。报告位于`output/reproduction/relocation_verification.json`，步骤日志为同目录下的`relocation.log`。

## 可选文档与编辑器

Word过程说明不是数值管线的必需步骤。可在独立Python环境安装`requirements-documents.txt`，运行`python scripts/build_project_roadmap.py`生成文档。Windows可通过`powershell -File scripts/render_project_roadmap.ps1`调用已安装的Microsoft Word导出供检查的PDF，再运行`python scripts/rasterize_project_roadmap.py`逐页栅格化。其他系统可用自身的文档渲染器，将PDF保存在`output/document_qa/project_roadmap/project-roadmap.pdf`后执行同一栅格化步骤。文档渲染后端与字体不同可能影响分页，不能跳过目视核验。

VS Code工作区不固定Git、conda、Python和TeX的安装位置。首次打开时通过“Python: Select Interpreter”选择自己的`mc-base`环境；Git与`latexmk`从PATH发现。QGIS、TeX Live、Word等为相应用途的可选工具，不是核心Python分析必须安装的依赖。Origin和PyTorch继续暂缓。
