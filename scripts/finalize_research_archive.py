"""Build curated public research evidence from existing local outputs, without simulation.

No raw rasters, vectors, WRF arrays, state caches or private collaboration packages
are copied. Run after restoring the local analysis outputs listed below.
"""
from pathlib import Path
import csv
import hashlib
import json
import re
import shutil
import subprocess

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs'
PUB = ROOT / 'support_materials/research'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p, text):
    p = ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip()+'\n', encoding='utf-8')


def table(p, rows):
    p = ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(p, index=False, encoding='utf-8-sig')


def main():
    # Archive the actual previous tracked documentation, not a rewritten history.
    for name in ['README.md', 'PROGRESS.md']:
        p = DOC/'archive'/('pre-finalization-'+name)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(subprocess.check_output(['git','show','e8806ef:'+name], cwd=ROOT))
    sources = {
      'd02': ('output/wrf_d02_integration', ['q1_weather_windows.csv','q2_hydrothermal_scenarios.csv','q2_d02_minus_d01.csv','q2_5km_neighborhood.csv','grid_location_evidence.csv','q3_reliability.csv','figure_numeric_sources.csv','q1_weather_comparison.png','q1_antecedent_windows.png','q2_hydrothermal_comparison.png']),
      'q4_diagnosis': ('output/question4/convergence_diagnostics', ['convergence_experiments.csv','before_after_comparison.csv','cfl_sensitivity.csv','field_convergence.csv','front_threshold_summary.csv','interface_flux_diagnostics.csv','inlet_momentum_check.csv','convergence_diagnostics.png','terrain_profile_diagnostics.png']),
      'q4_algorithms': ('output/question4/algorithm_validation', ['grid_convergence_metrics.csv','run_index.csv','stage_comparison.csv','algorithm_grid_comparison.png','real_mass_position.png']),
      'q4_acceptance': ('output/question4/convergence_supplement', ['refinement_comparison.csv','grid_summary.csv','phase_comparison.csv','section_1000_comparison.csv','section_timing_and_volume.csv','section_1000_timeseries.csv','spatial_mass_timeseries.csv','stopping_evidence.csv','acceptance_supplement.png','velocity_and_peak_alignment.png']),
    }
    commands = {'d02':'python scripts/integrate_wrf_d02.py', 'q4_diagnosis':'python scripts/diagnose_question4_convergence.py',
                'q4_algorithms':'python scripts/summarize_question4_algorithms.py', 'q4_acceptance':'python scripts/supplement_question4_acceptance.py; python scripts/write_question4_acceptance_report.py'}
    manifest=[]
    for group, (directory, names) in sources.items():
        for name in names:
            src=ROOT/directory/name; dest=PUB/group/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,dest)
            manifest.append(dict(result_path=dest.relative_to(ROOT).as_posix(), source_path=src.relative_to(ROOT).as_posix(),
                sha256=sha(src), analysis=group, command=commands[group],
                input_provenance='docs/provenance.md; docs/data_catalog.md',
                algorithm_version='D02 integration' if group=='d02' else 'candidate/baseline identified per table; see code_versions.csv',
                units_timezone='BJT UTC+8; rainfall mm; temperature degC' if group=='d02' else 'relative seconds; distance m; depth m; discharge m3/s; not observed',
                limitation='descriptive nested model context; not causal validation' if group=='d02' else 'uncalibrated scenarios; overall dynamic convergence not established'))
    table('support_materials/research/results_manifest.csv',manifest)
    code=[]
    for p in sorted((ROOT/'scripts').glob('*.py')):
        code.append(dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p)))
    for p in sorted((ROOT/'config').glob('*')):
        if p.is_file(): code.append(dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p)))
    table('support_materials/research/code_versions.csv',code)
    # Raw metadata stays local. Publish only portable evidence about code and parameters.
    prov=json.loads((ROOT/'output/question4/convergence_supplement/run_provenance.json').read_text(encoding='utf-8'))
    assert prov['solver_sha256']==sha(ROOT/'scripts/question4_friction_candidate.py')
    prov.pop('python',None)
    write('support_materials/research/q4_acceptance/provenance.json',json.dumps(prov,ensure_ascii=False,indent=2))
    gate=json.loads((ROOT/'output/question4/algorithm_validation/standard_gate.json').read_text())
    gate.pop('python',None)
    write('support_materials/research/q4_algorithms/standard_gate.json',json.dumps(gate,indent=2))
    # Preserve failed-test history, remove machine paths only in public log copies.
    logs=[ROOT/'output/finalization_tests.log',ROOT/'output/finalization_portability.log',ROOT/'output/finalization_external_cwd.log',ROOT/'output/finalization_portability_activated.log']
    logs+=list((ROOT/'output/question4/algorithm_validation').glob('stage*_before.log'))
    for p in logs:
        if p.exists():
            text=p.read_text(encoding='utf-8-sig',errors='replace')
            text=text.replace(str(ROOT),'<PROJECT>').replace('D:\\miniforge3\\envs\\mc-base','<ENV>')
            text=re.sub(r'[A-Z]:\\Users\\[^\s"\n]+','<TEMP_PATH>',text)
            write('docs/validation/'+p.name,text)
    version=[]
    for row in manifest:
        version.append(dict(path=row['source_path'],sha256=row['sha256'],remote_at_start=False,
          publish_path=row['result_path'],action='curated copy; original unchanged',limitation=row['limitation']))
    for p in sorted((ROOT/'scripts').glob('*.py')):
        rel=p.relative_to(ROOT).as_posix()
        old=subprocess.run(['git','cat-file','-e','origin/codex/question4-dynamics:'+rel],cwd=ROOT,capture_output=True).returncode==0
        version.append(dict(path=rel,sha256=sha(p),remote_at_start=old,publish_path=rel,action='retain or add source',limitation='version-specific results'))
    table('docs/version_matrix.csv',version)
    figures=[dict(figure_id=f'F{i+1}',path=r['result_path'],source=r['source_path'],sha256=r['sha256'],
        caption=('WRF嵌套域模式水热背景；非实测，小时区间，不用于因果识别' if r['analysis']=='d02' else '一维数值实验与网格敏感性；非真实灾害验证；候选与基线分开'),
        algorithm=r['algorithm_version'],status='existing computed figure; no new experiment') for i,r in enumerate([x for x in manifest if x['result_path'].endswith('.png')])]
    table('docs/figure_manifest.csv',figures)
    refs=[
      ('TPDC','https://data.tpdc.ac.cn/','JS页面未取得具体再分发许可；原始及逐格数据不发布','官方气象/GIS数据；保留本地来源索引'),
      ('2019 DEM','https://zenodo.org/records/22911264','2026-10-29已核实CC BY-NC 4.0；原始Pléiades影像另需CNES许可','Etienne Berthier; v2；页面建议引用DOI与记录DOI不同，引用时标版本'),
      ('post-event DEM','https://zenodo.org/records/22842746','2026-10-29已核实CC BY-NC 4.0；原始影像©2026 Vantor','David Shean; Shashank Bhushan; v1.0'),
      ('geo-pera','https://github.com/geo-pera/bhotekoshi-2026-reconstruction/releases','v1.1来源保留；代码MIT不自动授予原始影像/所有派生数据许可','代码LICENSE已读；各数据资产条款需单独核验'),
      ('UNOSAT','https://unosat.org/products/4259/','JS页面未读得完整许可；不新增发布矢量或遥感图像','卫星判读非现场独立验证'),
      ('Voellmy analytical benchmarks','https://doi.org/10.5194/esurf-13-665-2025','2026-10-29出版页面核实；CC BY 4.0','Bonomelli, Pilotti, Farina (2025), Earth Surface Dynamics 13,665–681；非本地参数校准')]
    table('docs/data_sources.csv',[dict(source=a,url=b,verification=c,usage=d) for a,b,c,d in refs])
    write('docs/project_inventory.md','''# 研究成果盘点

整理前已fetch：main=3afaa11，codex/question4-dynamics=e8806ef；两者相差Q4动力学、许可补充、Q2/Q3技术版本三次提交。整理分支从e8806ef创建。
工作区已有Q4栅格采样修正和报告修改；新增D02审计/集成、候选求解器、诊断脚本、专项测试及内部资料。未跟踪研究文件已在仓库外ZIP备份。

逐项路径和SHA见version_matrix.csv，公开结果见../support_materials/research/results_manifest.csv。全部data、output和内部deliverables仍在本地，未移动或覆盖。
本地D02集成已实际完成；候选验收在convergence_supplement而不是candidate_submission。candidate_submission及question4-v2.md在整理前不存在。本次不创建虚假的正式v2，不提升候选为现场预测模型。
本次只归档已计算成果，不重跑大型模拟；初诊CSV、算法比较CSV和细网格CSV的行数由实际文件计数见validation.md。
''')
    write('docs/overview.md','''# 研究范围

研究2026年吉隆冰岩崩—碎屑流—泥石流—山洪灾害链。四部分依次为多源背景对照、分层条件评估、事件时间约束与条件传播、一维入沟后动力学。
Q1五因素属于案例背景差异；Q2不是本地校准概率；Q3不具备可靠95%区间及经验覆盖率；Q4是未校准的有限体积数值实验。项目不是业务预报系统，也不是全链条三维重建。
历史题目技术报告保留在question1-v1.md至question4-v1.md，含当时资料状态。当前研究入口以README、methodology、validation和limitations为准。
''')
    write('docs/methodology.md','''# 方法与算法版本

Q1：QC/缺失规则、同季同钟点历史比较、五类因素经验分位。新增WRF D01/D02描述，不更改排名。
Q2：源区失稳、沟道物源/水源转化、下游传播的条件分层；缺失水源保持未知。场景评分不代表概率。
Q3：区分冰崩起始、转化阶段、物理触发、到达。模式起报不等于公开可得；反推速度的条件到达不是独立预测。
Q4：状态h、q=hu，质量与动量守恒，HLL通量、水静力重构、Voellmy摩擦、CFL时步。旧版源码question4_dynamics_v1_reference.py保留，question4_dynamics.py仅已有像元取样floor修正；build_question4_simulation.py没有切换到candidate。
question4_boundary_candidate.py检验入口质量/动量一致性；question4_friction_candidate.py为静摩擦平衡候选。缓存由源码SHA与输入数组SHA隔离。固定候选SHA和参数见../support_materials/research/q4_acceptance/provenance.json。
候选参考V=600000m³、B=100m、T=120s、入口h=3m、μ=0.1、ξ=300m/s²、窗口1800s，均为未本地校准假设，不随网格调整。6.25m细化共享25m母剖面，不增加观测信息。
''')
    write('docs/limitations.md','''# 科学与数值限制

- 单事件、84个历史空间点缺可靠时刻标签，不能制造小时监督标签。
- D02非现场观测；A/B共格点；24h降水窗从模式起报后2h开始；发布与生成时间未知。
- 模式雪/融雪为零不证明真实冰川无融水。SMOIS不可冒充SH2O或坡体孔压。
- 源区强度、真实水源/流量/入沟体积、摩阻与河道断面均未本地校准。
- Q3的95%触发预测区间、经验覆盖率和业务预警提前量无法可靠估计。赛题10:30与其他阶段资料语义冲突未解决。
- 候选Q4部分末时空间指标接近，不证明整体严格收敛；峰值速度、早期动量和断面过程仍敏感。
- 模拟h不是灾后堆积厚度。模型不包含入沟前冰崩、多相转换、侵蚀挟带、二维漫流，不能解释为现场22km重建。
- 独立观测验证、输入许可和文献参数可迁移性不能由单元测试通过替代。
''')
    write('docs/data_catalog.md','''# 数据来源与发布边界

原始附件按config/input-manifest.json放入data/附件/；WRF D01放data/wrfout_d01_2026-08-25_00_00_00，D02由review_wrf_d02.py --d02 <合法取得的文件>传入。
中心线及v1.1产品放data/supplementary/geo-pera-v1.1/；其余空间输入路径沿用config/question4-simulation.json和历史new-evidence-review.md。不得以地形版本不同的文件静默替代。
来源和本次许可检查见data_sources.csv。灾前/灾后DEM为CC BY-NC 4.0，图像版权独立；本仓库不新增分发DEM、正射影像或矢量。geo-pera代码MIT不等同其全部数据MIT。
TPDC与UNOSAT完整资产再分发许可本次未取得，不发布WRF原网格、站点原始逐时大表或完整卫星边界。新增公开内容限研究计算摘要、情景指标与原创分析图，不授予第三方数据新的许可。涉及DEM衍生的研究图表保留非商业及署名来源约束，商业复用应另核许可。
本仓库代码许可证尚未经权利人选择；未自动加入MIT/Apache或虚构作者署名。公开可读不等于获得无限制再利用许可。
''')
    write('docs/ai_assistance.md','''# AI辅助说明

本项目使用Codex/ChatGPT辅助数据审计脚本、模型实现、测试设计、错误诊断、图表和研究文档整理；研究需求、资料提供与科学判断由项目参与者负责。不能把AI辅助实现描述为独立人工验证。
原始聊天、私人账号和协作任务包不公开；不编造完整交互历史、工具模型版本、人工签字或未发生的验证。准确模型版本与逐次采纳过程没有完整公开记录。
本次归档含AI辅助索引及文档编写，数值引用来自实际文件；可执行检查的日志与科学审核状态分开记录。
''')
    write('docs/provenance.md','''# 输入、算法与结果追溯

support_materials/research/results_manifest.csv记录每个公开复制件的原相对路径、SHA、命令和解释限制；code_versions.csv冻结源代码和配置SHA。复制件数值未修改。
D02原始文件SHA由本地output/wrf_d02_review/metadata.json记录。原审计时间与全球属性不证明产品事前公开。
Q4原状态缓存由q4_solver_registry.py对求解器源码和输入数组生成指纹；真实床面及状态缓存不随Git分发。公开provenance.json保留候选SHA、床面SHA、参数和相对缓存位置，移除机器解释器路径。
研究期间提供的10:52、10:54:19—10:55:10、10:59属于待独立核验阶段时间资料；来源类型为参与者提供而非本项目现场测量，详细内部来源仍保留在原始本地证据表。
本次无新模拟结果；复制图件的Git版本由最终整理提交固定。Git提交号与文件SHA互补，不以文件修改时间证明科研版本。
''')
    write('docs/reproducibility.md','''# 复现

环境：conda env create -f environment.yml，然后conda activate mc-base。Windows精确历史环境另有environment.win-64.lock.txt；它不是跨平台锁。新增专项检查在Python 3.12环境执行。

不需要原始数据：python -m unittest discover -s tests -v。测试包含人工地形、入口边界、静止/干湿、质量守恒、缓存隔离及时间窗；不能以通过代替真实地形全面收敛。
仅检查工作流：python scripts/run_pipeline.py --dry-run。从外部目录调用脚本绝对位置或相对位置同样定位仓库根目录；代码不固定个人盘符。

完整外部数据工作流按依赖执行：run_pipeline.py → prepare_event_context.py → build_question2_assessment.py → build_question3_forecast.py；Q1入口complete_question1.py，历史Q1说明见question1-v1.md。Q4旧版入口build_question4_simulation.py，切勿与候选混用。
候选流程：diagnose_question4_convergence.py生成共同床面；run_question4_algorithm_validation.py --solver baseline / boundary / candidate分别计算标准地形；gate_question4_candidate.py基本门槛通过后，再对各版本使用--terrain real；summarize_question4_algorithms.py汇总；supplement_question4_acceptance.py与write_question4_acceptance_report.py补充细网格。真实实验还需event_context、DEM及中心线，公开CSV不是这些输入的替代品。既有入口的标准长实验仍读取event_context域长；无数据用户运行单元标准试验即可。
D02：python scripts/review_wrf_d02.py --d02 <文件路径>，再python scripts/integrate_wrf_d02.py。输出output/wrf_d02_review和output/wrf_d02_integration。审计需D01原文件；集成只需已审计轻量表。再运行python scripts/finalize_research_archive.py更新公开精选复制件；这是本地归档工具，不是无数据复现入口。
本次只实际运行现有测试与外部工作目录检查，完整WRF审计和长时间动力学引用先前已执行日志，没有宣称全部重算。
''')
    write('docs/changelog.md','''# 研究版本历史

- 3afaa11：较早main，事件阶段时间整合。
- 04144c1、6382235：Q4旧版动力学及来源许可说明。
- e8806ef：Q2/Q3技术首版，后续整理的基线。
- 本整理分支：发布已存在的D02审计/集成、Q4初诊与边界/静摩擦候选、细网格验收及失败记录。没有新的科学实验，没有替换正式旧求解器。
- README与PROGRESS前版存docs/archive；历史技术报告保留内容，当前文档入口使用中性研究语言。main在PR合并前仍是旧版，不能声称已更新默认分支。
''')
    write('docs/archive/README.md','''# 历史记录

pre-finalization-README.md与pre-finalization-PROGRESS.md来自e8806ef，保留当时措辞和资料状态，不作为当前进度。
docs/question*-v*.md及既有计划文件是历史技术/过程记录，包含未通过的实验和当时任务描述；正式研究入口为根README与docs中的新方法、验证及局限说明。未发布内部协作包和聊天记录。
''')
    write('docs/figures.md','# 图表索引\n\n全部新图及SHA见[研究图表清单](figure_manifest.csv)。\n\n'+'\n\n'.join(f"### {r['figure_id']} {r['caption']}\n\n![{r['figure_id']}](../{r['path']})\n\n算法：{r['algorithm']}；原件：`{r['source']}`。" for r in figures))
    write('README.md','''# 吉隆泥石流灾害链研究

本项目整理2026年吉隆冰岩崩—碎屑流—泥石流—山洪灾害链的多源数据分析、分层条件评估、时间情景和一维动力学实验。研究阶段已结束；本仓库用于长期追溯和复现，不是经过现场校准的业务预报系统。

## 研究结果与边界

| 模块 | 已实现 | 不能据此宣称 |
|---|---|---|
| Q1 | 五类候选因素背景比较；D01/D02模式天气 | 普适因果因素排名或源区实测降水 |
| Q2 | 地形、物源与未知水源的分层条件评估 | 本地校准临界阈值或触发概率 |
| Q3 | 时间证据与检测后条件传播 | 已验证95%触发区间、覆盖率或业务提前量 |
| Q4 | 基线/候选一维有限体积、质量收支、网格试验 | 全链重建、整体严格收敛或实测堆积厚度 |

D02源区最近格点截至8月26日10:00北京时间前24h模式降水26.095mm，D01为10.948mm；D02口岸4.329mm。源区09—10h最近格点两域均0，但不代表整个源区灾前无雨。24h窗口起点距模式启动仅2h。A/B共享D02格点；两个嵌套域不是独立模型验证。

候选Q4在25/12.5/6.25m下的末时流深较接近，峰值速度和断面过程仍敏感；候选保留为探索性版本，没有替换旧版。所有结论限定于固定假设入沟条件。

## 快速开始

```console
conda env create -f environment.yml
conda activate mc-base
python -m unittest discover -s tests -v
python scripts/run_pipeline.py --dry-run
```

单元试验无需原始大数据。完整地理/气象实验需要合法取得外部数据，按[复现说明](docs/reproducibility.md)放置；不能直接用本仓库轻量图件替代原始输入。

## 阅读路径

- [研究范围](docs/overview.md) · [方法与版本](docs/methodology.md) · [数值验证](docs/validation.md) · [科学限制](docs/limitations.md)
- [数据来源与许可](docs/data_catalog.md) · [追溯关系](docs/provenance.md) · [版本历史](docs/changelog.md) · [AI辅助](docs/ai_assistance.md)
- [图表](docs/figures.md) · [研究结果索引](support_materials/research/results_manifest.csv)
- [成果盘点](docs/project_inventory.md) · [整理验收报告](docs/project_closeout_report.md)

scripts/config/tests保留现有路径；support_materials/research只含精选研究结果；data/output不整体分发；docs/archive与历史报告保留不利结果和研究过程。
代码许可证尚未由权利人确定。第三方数据、影像与派生产品遵循各自许可，不能因代码公开而视作无限制授权。
''')
    write('PROGRESS.md','''# 研究状态

研究阶段已结束。当前完成状态按“已实现／条件情景／未独立验证／无法估计”记录，不使用完成百分比。
详见[研究概览](README.md)、[验证](docs/validation.md)、[整理报告](docs/project_closeout_report.md)。旧进度原文在[归档](docs/archive/pre-finalization-PROGRESS.md)。
D02已完成审计和Q1/Q2/Q3补充；Q4已完成候选数值比较及6.25m补充验收，整体动态收敛和现场有效性未建立。Q3统计95%指标不可可靠估计。没有新增未校准的确定性结论。
''')
    print('Curated',len(manifest),'results; code/config hashes',len(code))


if __name__=='__main__':
    main()
