# 数据来源与发布边界

原始附件按config/input-manifest.json放入data/附件/；WRF D01放data/wrfout_d01_2026-08-25_00_00_00，D02由review_wrf_d02.py --d02 <合法取得的文件>传入。
中心线及v1.1产品放data/supplementary/geo-pera-v1.1/；其余空间输入路径沿用config/question4-simulation.json和历史new-evidence-review.md。不得以地形版本不同的文件静默替代。
来源和本次许可检查见data_sources.csv。灾前/灾后DEM为CC BY-NC 4.0，图像版权独立；本仓库不新增分发DEM、正射影像或矢量。geo-pera代码MIT不等同其全部数据MIT。
TPDC与UNOSAT完整资产再分发许可本次未取得，不发布WRF原网格、站点原始逐时大表或完整卫星边界。新增公开内容限研究计算摘要、情景指标与原创分析图，不授予第三方数据新的许可。涉及DEM衍生的研究图表保留非商业及署名来源约束，商业复用应另核许可。
本仓库代码许可证尚未经权利人选择；未自动加入MIT/Apache或虚构作者署名。公开可读不等于获得无限制再利用许可。
