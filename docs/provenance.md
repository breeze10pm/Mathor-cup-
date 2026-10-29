# 输入、算法与结果追溯

support_materials/research/results_manifest.csv记录每个公开复制件的原相对路径、SHA、命令和解释限制；code_versions.csv冻结源代码和配置SHA。复制件数值未修改。
D02原始文件SHA由本地output/wrf_d02_review/metadata.json记录。原审计时间与全球属性不证明产品事前公开。
Q4原状态缓存由q4_solver_registry.py对求解器源码和输入数组生成指纹；真实床面及状态缓存不随Git分发。公开provenance.json保留候选SHA、床面SHA、参数和相对缓存位置，移除机器解释器路径。
研究期间提供的10:52、10:54:19—10:55:10、10:59属于待独立核验阶段时间资料；来源类型为参与者提供而非本项目现场测量，详细内部来源仍保留在原始本地证据表。
本次无新模拟结果；复制图件的Git版本由最终整理提交固定。Git提交号与文件SHA互补，不以文件修改时间证明科研版本。

code_versions.csv同时记录本地原字节SHA与Git规范化blob SHA；数值求解器及精选结果保持原字节，文档换行不影响科学结果。
