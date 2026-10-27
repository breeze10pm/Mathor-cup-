# 数据来源与解释边界

用户于2026年10月27日确认，项目 `data/附件/` 中8组压缩包均为本届官方原始附件，
当前没有另外提供QC代码说明或数据手册。审计脚本对原始包只读，并记录SHA-256。

附件2内部的 `数据引用-数据来源.doc` 是旧版Word二进制文档。其正文指明数据来源为
ERA5-Land再分析数据集，来自Copernicus Climate Data Store，引用产品为：

Muñoz Sabater et al. (2024). *ERA5-land post-processed daily-statistics from 1950 to present*.
DOI: [10.24381/cds.e9c9c792](https://doi.org/10.24381/cds.e9c9c792).

[CDS产品说明](https://cds.climate.copernicus.eu/datasets/derived-era5-land-daily-statistics?tab=overview)
将原始2米气温单位列为K，并允许选择不同UTC偏移计算日统计量。
官方附件中的Excel列标题没有单位，表内存在负数，不可视作未经转换的开尔文值。
摄氏温度转换、日界线与县域汇总/采样方式尚未在附件中明确，审计保留表内数值，
不再自行减273.15，不指定UTC+8日界线。ERA5-Land再分析数据用于历史背景分析，
不当作预警时刻已经发布的天气预报。

小时观测CSV列标题提供多数物理量的单位，但没有站点经纬度、时区、小时区间
起止语义、降水累计区间或QC码定义。审计把9999.9等常见哨兵值作为候选缺测诊断，
单独记录非数值`NAN`标记；不据此宣称最终质量验收。

历史灾害图层的“影像Time”“解译Time”是图层中实际日期字段；现有附件没有给出
可以直接认定为灾害发生时间的字段。不能把影像/解译时间用作触发时间标签。
其他空间数据的来源与分辨率以空间审计报告和各自元数据为准。
