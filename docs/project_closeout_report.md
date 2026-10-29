# 项目整理验收报告

整理分支codex/project-finalization，从e8806ef建立；远程main基线3afaa11。推送与PR状态在最后一次交付记录中补全，未自动合并。

已整理：D02真实已计算的源区/口岸窗口与图件；Q4初诊、版本隔离、边界及静摩擦候选、细网格验收。34个精选结果复制件保留数值与SHA；原data/output未修改。代码、配置、数值和图表索引统一。旧README/PROGRESS归档，内部协作包留本地。
候选SHA与母床面指纹在support_materials/research/q4_acceptance/provenance.json；不创建虚假的candidate_submission或正式v2，不将候选替换旧基线。

复现：91项本地测试通过；91项无原数据副本测试通过；外部工作目录dry-run通过。首次未激活原生库路径发生进程退出，记录保留。完整长实验本次没有重跑；表中统计源自先前结果。

论文：docs/paper中的两层版本对照、数字主表、图表和来源核验完成。未取得论文正文，未声称已经修改最终文稿；相对上次增量说明没有新增科学实验。

仅本地：原始遥感/DEM/WRF、完整GIS、状态NPZ缓存、内部资料包、许可未明的原始表格、真实共同床面。第三方来源与许可核查见data_catalog.md。代码许可证未由权利人指定，不擅自授权。
遗留：Q3统计95%指标不可可靠估计；Q2水源阈值未本地校准；Q4速度、过程线及现场准确性未验证。main在PR合并前仍为旧入口。

## 远程交付状态

已推送分支：https://github.com/breeze10pm/Mathor-cup-/tree/codex/project-finalization
批次提交：9fd88e1（D02）、14e1c48（Q4算法与验收）、138eb8c（研究文档与精选证据）；后续换行及交付记录修正在本分支最新提交。
GitHub连接器创建PR实际返回HTTP 403：Resource not accessible by integration。本机未发现gh CLI。PR尚未创建，没有伪造PR编号，也未合并main。可由有权限账号从以下预填比较页创建：
https://github.com/breeze10pm/Mathor-cup-/compare/main...codex/project-finalization?expand=1
main仍为3afaa11。当前没有GitHub Actions工作流，因此没有远程CI通过声明；实际测试为本地和独立无数据副本。

敏感信息常见凭据模式扫描未命中；没有超过5MiB的跟踪文件，没有新增执行权限或符号链接。此检查不能保证排除一切未知秘密。新增34个结果Git blob逐字节SHA与原输出相符；对这些数据及求解器快照禁用Git换行转换，其余文档采用LF，避免平台换行造成伪差异。
原始DEM/影像/WRF/完整GIS和NPZ缓存仍在本地。内部deliverables以及6份未跟踪计划仅本地保留并已备份；未无差别上传。
