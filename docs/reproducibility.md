# 复现

环境：conda env create -f environment.yml，然后conda activate mc-base。Windows精确历史环境另有environment.win-64.lock.txt；它不是跨平台锁。新增专项检查在Python 3.12环境执行。

不需要原始数据：python -m unittest discover -s tests -v。测试包含人工地形、入口边界、静止/干湿、质量守恒、缓存隔离及时间窗；不能以通过代替真实地形全面收敛。
仅检查工作流：python scripts/run_pipeline.py --dry-run。从外部目录调用脚本绝对位置或相对位置同样定位仓库根目录；代码不固定个人盘符。

完整外部数据工作流按依赖执行：run_pipeline.py → prepare_event_context.py → build_question2_assessment.py → build_question3_forecast.py；Q1入口complete_question1.py，历史Q1说明见question1-v1.md。Q4旧版入口build_question4_simulation.py，切勿与候选混用。
候选流程：diagnose_question4_convergence.py生成共同床面；run_question4_algorithm_validation.py --solver baseline / boundary / candidate分别计算标准地形；gate_question4_candidate.py基本门槛通过后，再对各版本使用--terrain real；summarize_question4_algorithms.py汇总；supplement_question4_acceptance.py与write_question4_acceptance_report.py补充细网格。真实实验还需event_context、DEM及中心线，公开CSV不是这些输入的替代品。既有入口的标准长实验仍读取event_context域长；无数据用户运行单元标准试验即可。
D02：python scripts/review_wrf_d02.py --d02 <文件路径>，再python scripts/integrate_wrf_d02.py。输出output/wrf_d02_review和output/wrf_d02_integration。审计需D01原文件；集成只需已审计轻量表。再运行python scripts/finalize_research_archive.py更新公开精选复制件；这是本地归档工具，不是无数据复现入口。
本次只实际运行现有测试与外部工作目录检查，完整WRF审计和长时间动力学引用先前已执行日志，没有宣称全部重算。
