# 附件3—8内嵌元数据证据复核

仅只读本地官方原始附件；不联网、不建模、不插补，不改旧审计、脚本或主报告。原始包及成员SHA256、完整XML节点、DOCX XML、173个TIFF头和NetCDF全部属性保存在 `output/metadata_review/local_spatial_evidence.json`。

F：附件明确文本/属性/存储事实，不自动升级为外部真实性认证；I：字段名、数值规律、上下文推断；U：本地无明确依据。U项引用最接近的真实源文来界定问题，不能把“未找到”伪装成官方原句。

关键纠正：影像Time/解译Time没有业务定义；DEM明确有Clip处理历史；人口数不得称户籍/家庭户人口；dhdt数值单位/误差σ在本地未明确。空间附件不能替代气象QC、时区或降水累计说明。

## 逐项证据

### S01 [F] 附件3区域与事件背景日

官方摘要称围绕2026年8月26日吉隆口岸冰岩崩源区所在冰川构建200km区域，整理2000—2020年高程变化。

- 包：`（3）日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集 (2000-2020).rar`；成员：`西藏日喀则市吉隆县特大洪水—200km周围内的冰川和冰川厚度变化数据集/文档说明.docx`。
  字段/属性：`word/document.xml 段2`；准确摘录：`本数据集以2026年8月26日吉隆口岸冰岩崩源区所在冰川为中心，构建半径200 km区域范围，整理该区域冰川空间分布及2000—2020年冰川表面高程变化数据。`。

限制：仅提供背景事件日历日期及区域定义；未给事件时刻、时区或历史逐事件目录。

### S02 [F] 附件3变化率时期与产品

官方摘要明确4个5年时期、dhdt_UTM/dhdt_GCS变化率及dhdt_err_UTM误差产品。

- 包：`（3）日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集 (2000-2020).rar`；成员：`西藏日喀则市吉隆县特大洪水—200km周围内的冰川和冰川厚度变化数据集/文档说明.docx`。
  字段/属性：`word/document.xml 段3`；准确摘录：`2000—2005年、2005—2010年、2010—2015年和2015—2020年四个时期冰川表面高程变化率数据。`。
- 包：`（3）日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集 (2000-2020).rar`；成员：`西藏日喀则市吉隆县特大洪水—200km周围内的冰川和冰川厚度变化数据集/文档说明.docx`。
  字段/属性：`word/document.xml 段3`；准确摘录：`UTM投影下的高程变化率（dhdt_UTM）、地理坐标系下的高程变化率（dhdt_GCS）以及UTM投影下的高程变化率误差（dhdt_err_UTM）`。

限制：四个窗口是长期变化统计时期，不是4次灾害发生日期。

### S03 [U] 附件3具体率单位及误差/QC

m/year、误差置信水平、1σ与质量筛选规则在本地摘要和168个TIFF元数据中未被明确给出。

- 包：`（3）日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集 (2000-2020).rar`；成员：`西藏日喀则市吉隆县特大洪水—200km周围内的冰川和冰川厚度变化数据集/文档说明.docx`。
  字段/属性：`word/document.xml`；准确摘录：`冰川表面高程变化率数据`。
- 包：`（3）日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集 (2000-2020).rar`；成员：`西藏日喀则市吉隆县特大洪水—200km周围内的冰川和冰川厚度变化数据集/13_14_15_rgi60_2000-01-01_2005-01-01/dhdt_UTM/N27E086_2000-01-01_2005-01-01_dhdt_UTM45_UTM45.tif`。
  字段/属性：`TIFF band.units`；准确摘录：`None`。

限制：文档只写变化率/误差；不能仅凭dhdt或引用产品常识补具体数值单位。

### S04 [F] NetCDF气候态/截距

vx/vy属性明确2014—2024气候态、年均速度拟合、2018-01-01截距。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`vx.description`；准确摘录：`climatological [2014-2024] vx determined by a weighted least squares line fit, described by an offset and slope, to mean annual vx values. The climatology uses a time-intercept of January 1, 2018.`。
- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`v.standard_name`；准确摘录：`climatological [2014-2024] velocity`。

限制：2018是拟合截距而非一次实测时间；气候态不能当2026临灾实时速度。

### S05 [F] NetCDF参考网格/重采样

文件明确速度双线性插值到30m参考网格，GeoTransform为30m步长，UTM45N。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`global.velocity_resampling`；准确摘录：`bilinear to the 30 m reference grid`。
- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`spatial_ref.GeoTransform`；准确摘录：`353442.5 30.0 0.0 3132057.5 0.0 -30.0`。
- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`spatial_ref.crs_wkt`；准确摘录：`AUTHORITY["EPSG","32645"]`。

限制：不证明源速度原生观测分辨率为30m；处理顺序/源分辨率未给。

### UNIT_dem [F] NetCDF dem单位

dem units属性明确为 m。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`dem.units`；准确摘录：`m`。

限制：仅是文件声明单位，不证明观测精度或实际获取日期。

### UNIT_slope [F] NetCDF slope单位

slope units属性明确为 degree。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`slope.units`；准确摘录：`degree`。

限制：仅是文件声明单位，不证明观测精度或实际获取日期。

### UNIT_thickness [F] NetCDF thickness单位

thickness units属性明确为 m。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`thickness.units`；准确摘录：`m`。

限制：仅是文件声明单位，不证明观测精度或实际获取日期。

### UNIT_vx [F] NetCDF vx单位

vx units属性明确为 meter/year。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`vx.units`；准确摘录：`meter/year`。

限制：仅是文件声明单位，不证明观测精度或实际获取日期。

### UNIT_vx_amp [F] NetCDF vx_amp单位

vx_amp units属性明确为 meter/year。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`vx_amp.units`；准确摘录：`meter/year`。

限制：仅是文件声明单位，不证明观测精度或实际获取日期。

### UNIT_vy [F] NetCDF vy单位

vy units属性明确为 meter/year。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`vy.units`；准确摘录：`meter/year`。

限制：仅是文件声明单位，不证明观测精度或实际获取日期。

### UNIT_vy_amp [F] NetCDF vy_amp单位

vy_amp units属性明确为 meter/year。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`vy_amp.units`；准确摘录：`meter/year`。

限制：仅是文件声明单位，不证明观测精度或实际获取日期。

### UNIT_v [F] NetCDF v单位

v units属性明确为 meter/year。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`v.units`；准确摘录：`meter/year`。

限制：仅是文件声明单位，不证明观测精度或实际获取日期。

### UNIT_v_amp [F] NetCDF v_amp单位

v_amp units属性明确为 meter/year。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`v_amp.units`；准确摘录：`meter/year`。

限制：仅是文件声明单位，不证明观测精度或实际获取日期。

### UNIT_x [F] NetCDF x单位

x units属性明确为 m。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`x.units`；准确摘录：`m`。

限制：仅是文件声明单位，不证明观测精度或实际获取日期。

### UNIT_y [F] NetCDF y单位

y units属性明确为 m。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`y.units`；准确摘录：`m`。

限制：仅是文件声明单位，不证明观测精度或实际获取日期。

### S06 [F] NetCDF缺失值声明/字段清单

decode_cf=False核对显示全部浮点数据及坐标变量的_FillValue为NaN；变量清单无QC字段。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`thickness._FillValue`；准确摘录：`NaN`。
- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`variables`；准确摘录：`dem, slope, thickness, spatial_ref, vx, vx_amp, vy, vy_amp, v, v_amp, glacier_mask, y, x`。

限制：NaN仅为缺失编码；不能解释为质量不合格或合格。文件中无flag_values/flag_meanings。

### S07 [F] NetCDF冰厚来源

thickness描述明确引用Farinotti et al. (2019)的consensus estimate。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`thickness.description`；准确摘录：`Ice thickness data from A consensus estimate for the ice thickness distribution of all glaciers on Earth (Farinotti et al., 2019).`。

限制：引文年份不是当地实测年；不能称2026年实时冰厚。

### S08 [U] NetCDF获取时间/时区

dem/slope/thickness获取日期、源速度原生分辨率及时间的时区未明确。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`global.source`；准确摘录：`dem_30m.tif, slope_30m.tif, thickness_30m.tif`。
- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`global.velocity_source`；准确摘录：`ITS_LIVE v2.1`。

限制：无time维/坐标；压缩包标题“冰崩前”不足以给逐变量补采集时间。

### S09 [F] DEM精确处理时间标签

DEM XML lineage/Process Date=20260826、Time=171843，工具Clip，输入GeBainiDEM_30M.tif。

- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`/metadata/Esri/DataProperties/lineage/Process/@Date`；准确摘录：`20260826`。
- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`/metadata/Esri/DataProperties/lineage/Process/@Time`；准确摘录：`171843`。
- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`/metadata/Esri/DataProperties/lineage/Process/text()`；准确摘录：`Clip GeBainiDEM_30M.tif "85.189755774642 28.2455345097983 85.6941438166103 28.5643822845793" Y:\20260826吉隆口岸泥石流\02基础地理数据\DEM\DEM.tif New_Shapefile -3.276700e+04 NONE MAINTAIN_EXTENT`。

限制：这是明确裁剪处理记录，未给输入DEM采集时间、处理时区或灾前/灾后地形状态。

### DEM_CreaDate [F] DEM CreaDate

XML在Esri节点存储 CreaDate=20260826。

- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`/metadata/Esri/CreaDate`；准确摘录：`20260826`。

限制：F仅确认精确标签和值；创建/同步/修改的对象不能自动解释成地形观测采集，亦无时区声明。

### DEM_CreaTime [F] DEM CreaTime

XML在Esri节点存储 CreaTime=17184300。

- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`/metadata/Esri/CreaTime`；准确摘录：`17184300`。

限制：F仅确认精确标签和值；创建/同步/修改的对象不能自动解释成地形观测采集，亦无时区声明。

### DEM_SyncDate [F] DEM SyncDate

XML在Esri节点存储 SyncDate=20260826。

- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`/metadata/Esri/SyncDate`；准确摘录：`20260826`。

限制：F仅确认精确标签和值；创建/同步/修改的对象不能自动解释成地形观测采集，亦无时区声明。

### DEM_SyncTime [F] DEM SyncTime

XML在Esri节点存储 SyncTime=17184300。

- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`/metadata/Esri/SyncTime`；准确摘录：`17184300`。

限制：F仅确认精确标签和值；创建/同步/修改的对象不能自动解释成地形观测采集，亦无时区声明。

### DEM_ModDate [F] DEM ModDate

XML在Esri节点存储 ModDate=20260826。

- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`/metadata/Esri/ModDate`；准确摘录：`20260826`。

限制：F仅确认精确标签和值；创建/同步/修改的对象不能自动解释成地形观测采集，亦无时区声明。

### DEM_ModTime [F] DEM ModTime

XML在Esri节点存储 ModTime=17184300。

- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`/metadata/Esri/ModTime`；准确摘录：`17184300`。

限制：F仅确认精确标签和值；创建/同步/修改的对象不能自动解释成地形观测采集，亦无时区声明。

### S10 [U] DEM采集时序/源产品身份

2026-08-26是否采集日期、输入DEM是否灾前地形及输入产品详细身份均未知。

- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`lineage/Process`；准确摘录：`Clip GeBainiDEM_30M.tif`。

限制：不得把处理日或GeBainiDEM_30M文件名补成产品来源、采集日期。

### S11 [F] DEM水平/垂直单位、基准、nodata

水平单位Degree，波段单位metre，nodata=-32767；XML嵌入WKT垂直基准unknown。

- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`coordRef/csUnits`；准确摘录：`Angular Unit: Degree (0.017453)`。
- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif`。
  字段/属性：`band.units`；准确摘录：`metre`。
- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`RasterProperties/General/NoDataValue`；准确摘录：`-32767`。
- 包：`（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip`；成员：`DEM.tif.xml`。
  字段/属性：`coordRef/peXml`；准确摘录：`VERTCS["unknown",VDATUM["unknown"]`。

限制：输出格网水平单位是度，不是文件名所暗示的固定30m；垂直单位已给不等于垂直基准已知。

### HFIELD_影像Time [F] 历史 影像Time字段元数据

XML仅给字段名/别名影像Time、Date类型、宽度8等结构，未给attrdef/业务定义。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`eainfo/detailed/attr[影像Time]/attrlabl`；准确摘录：`影像Time`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`eainfo/detailed/attr[影像Time]/attrtype`；准确摘录：`Date`。

限制：Date是存储类型，不能从名称直接确定原始影像获取日、实际解译工作日或灾害发生日。

### HFIELD_解译Time [F] 历史 解译Time字段元数据

XML仅给字段名/别名解译Time、Date类型、宽度8等结构，未给attrdef/业务定义。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`eainfo/detailed/attr[解译Time]/attrlabl`；准确摘录：`解译Time`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`eainfo/detailed/attr[解译Time]/attrtype`；准确摘录：`Date`。

限制：Date是存储类型，不能从名称直接确定原始影像获取日、实际解译工作日或灾害发生日。

### HPROC_解译Time [F] 历史 解译Time赋值历史

XML保存3条给解译Time字段赋值的CalculateField记录。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process Date=20201110 Time=171337`；准确摘录：`CalculateField 面终3 解译Time "2020/9/25" VB #`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process Date=20201110 Time=183939`；准确摘录：`CalculateField 面终3 解译Time "2020/6/25" VB #`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process Date=20201110 Time=183955`；准确摘录：`CalculateField 面终3 解译Time "2020/7/25" VB #`。

限制：来源图层操作不保证只作用当前84条子集；操作日期不是灾害日期；赋值不会构成业务定义。完整操作保留JSON。

### HPROC_影像Time [F] 历史 影像Time赋值历史

XML保存33条给影像Time字段赋值的CalculateField记录。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process Date=20201110 Time=194635`；准确摘录：`CalculateField 面终3 影像Time "2017/11/11" VB #`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process Date=20201110 Time=194708`；准确摘录：`CalculateField 面终3 影像Time "2015/5/08" VB #`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process Date=20201110 Time=194820`；准确摘录：`CalculateField 面终3 影像Time "2017/10/17" VB #`。

限制：来源图层操作不保证只作用当前84条子集；操作日期不是灾害日期；赋值不会构成业务定义。完整操作保留JSON。

### HPROC_flag [F] 历史 flag赋值历史

XML保存1条给flag字段赋值的CalculateField记录。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process Date=20201106 Time=161216`；准确摘录：`CalculateField 泥石流流域\Polygons flag 1 VB #`。

限制：来源图层操作不保证只作用当前84条子集；操作日期不是灾害日期；赋值不会构成业务定义。完整操作保留JSON。

### HPROC_Resolution [F] 历史 Resolution赋值历史

XML保存1条给Resolution字段赋值的CalculateField记录。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process Date=20201110 Time=171547`；准确摘录：`CalculateField 面终3 Resolution "1m" VB #`。

限制：来源图层操作不保证只作用当前84条子集；操作日期不是灾害日期；赋值不会构成业务定义。完整操作保留JSON。

### S12 [I] 历史日期字段解释

中文字段名和赋值上下文提示解译Time与解译有关，影像Time与影像参考日期有关。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process`；准确摘录：`CalculateField 面终3 解译Time "2020/7/25" VB #`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process`；准确摘录：`CalculateField 面终3 影像Time "2017/11/11" VB #`。

限制：仅为推断；“获取日”“实际作业日”未明确，均不能充当灾害发生日期。

### S13 [F] 历史当前存储值

当前DBF解译Time全部84条为2020-07-25；影像Time范围2010-05-08至2017-11-11。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.dbf`。
  字段/属性：`解译Time`；准确摘录：`2020-07-25 (84 records)`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.dbf`。
  字段/属性：`影像Time`；准确摘录：`2010-05-08 00:00:00 — 2017-11-11 00:00:00`。

限制：存储值与业务定义分开；真实影像获取/解译日期未因此验证。

### S14 [U] 历史事件标签/QC/时区

没有明确定义的逐灾害发生时刻、时区或QC字典；flag=1的业务含义未知。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process`；准确摘录：`CalculateField 泥石流流域\Polygons flag 1 VB #`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`eainfo/detailed/attr[flag]/attrtype`；准确摘录：`Integer`。

限制：不能把flag=1直接当已发生事件、正样本或QC合格；不生成最终预测标签。

### S15 [F] 历史图层导出/元数据日期

XML明确ExportFeatures操作Date=20260827、Time=004633，mdDateSt=20260827。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process/@Date`；准确摘录：`20260827`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process/@Time`；准确摘录：`004633`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`lineage/Process/text()`；准确摘录：`ExportFeatures 面-中尼廊道吉隆泥石流 C:\Users\35208\Desktop\西藏日喀则市吉隆县泥石流灾害区历史灾点数据\西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`mdDateSt`；准确摘录：`20260827`。

限制：这是导出/元数据时间，不是2026-08-26灾害发生时刻；无时区。

### HISTORY_CreaDate [F] 历史图层 CreaDate

XML存储 CreaDate=20260826。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`/metadata/Esri/CreaDate`；准确摘录：`20260826`。

限制：只确认字段与值，不解释为事件或观测日期，无时区。

### HISTORY_CreaTime [F] 历史图层 CreaTime

XML存储 CreaTime=22425000。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`/metadata/Esri/CreaTime`；准确摘录：`22425000`。

限制：只确认字段与值，不解释为事件或观测日期，无时区。

### HISTORY_SyncDate [F] 历史图层 SyncDate

XML存储 SyncDate=20260827。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`/metadata/Esri/SyncDate`；准确摘录：`20260827`。

限制：只确认字段与值，不解释为事件或观测日期，无时区。

### HISTORY_SyncTime [F] 历史图层 SyncTime

XML存储 SyncTime=00463300。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`/metadata/Esri/SyncTime`；准确摘录：`00463300`。

限制：只确认字段与值，不解释为事件或观测日期，无时区。

### HISTORY_ModDate [F] 历史图层 ModDate

XML存储 ModDate=20260827。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`/metadata/Esri/ModDate`；准确摘录：`20260827`。

限制：只确认字段与值，不解释为事件或观测日期，无时区。

### HISTORY_ModTime [F] 历史图层 ModTime

XML存储 ModTime=00463300。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`/metadata/Esri/ModTime`；准确摘录：`00463300`。

限制：只确认字段与值，不解释为事件或观测日期，无时区。

### S16 [U] 历史其他分类、长度、频率解释

类型/频率/规模/Area/DisFrmFlt/主沟长/扇宽等字段未附代码域、阈值、长度面积单位或QC规则。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`eainfo/detailed/attr[频率]/attrlabl`；准确摘录：`频率`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`eainfo/detailed/attr[Area]/attrtype`；准确摘录：`Double`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`eainfo/detailed/attr[类型]/attrlabl`；准确摘录：`类型`。

限制：可描述原始字符串和数值，不能造频次阈值、单位或因果标签；Resolution赋1m不证明原影像真实分辨率。

### S17 [U] 土地覆盖类别/QC/日期

附件5只有4个TIFF，无类码名称、颜色表、QC字典或年度成图/获取时刻定义。

- 包：`（5）西藏日喀则市吉隆县泥石流灾害区土地覆盖数据（2020-2023）.zip`；成员：`jilong_LUCD_2020.tif`。
  字段/属性：`band descriptions / color_table`；准确摘录：`None / None`。

限制：文件名2020—2023是年份标签，不足以确定日期/时区或对应观测窗口；不套用常见分类产品字典。

### S18 [F] 土地覆盖nodata及金字塔标签

四个TIFF声明nodata=0；2020 TIFF的Esri.PyramidResamplingType=NEAREST。

- 包：`（5）西藏日喀则市吉隆县泥石流灾害区土地覆盖数据（2020-2023）.zip`；成员：`jilong_LUCD_2020.tif`。
  字段/属性：`nodata`；准确摘录：`0.0`。
- 包：`（5）西藏日喀则市吉隆县泥石流灾害区土地覆盖数据（2020-2023）.zip`；成员：`jilong_LUCD_2020.tif`。
  字段/属性：`Esri.PyramidResamplingType`；准确摘录：`NEAREST`。

限制：只证明nodata编码及金字塔重采样标签；不能推定分类生产/年度配准重采样方法。

### S19 [F] 人口原始字段

DBF原始字段合计=17536、人口数=16155、户数=4845、户规模=3.33，图层仅1条县级要素。

- 包：`（8）西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据.zip`；成员：`西藏日喀则市吉隆县第七次人口普查数据/西藏日喀则市吉隆县第七次人口普查数据.dbf`。
  字段/属性：`合计/人口数/户数/户规模`；准确摘录：`17536 / 16155 / 4845 / 3.33`。

限制：存在这些字段不等于其统计口径已有官方定义；本包无说明文档或shp.xml。

### S20 [I] 人口数值相容性

人口数/户数=3.334365325，四舍五入两位与户规模3.33相符；男+女和城镇+乡村均等于17536。

- 包：`（8）西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据.zip`；成员：`西藏日喀则市吉隆县第七次人口普查数据/西藏日喀则市吉隆县第七次人口普查数据.dbf`。
  字段/属性：`人口数/户数/户规模`；准确摘录：`16155 / 4845 / 3.33`。
- 包：`（8）西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据.zip`；成员：`西藏日喀则市吉隆县第七次人口普查数据/西藏日喀则市吉隆县第七次人口普查数据.dbf`。
  字段/属性：`男/女/城镇人/乡村人`；准确摘录：`9338 / 8198 / 5015 / 12521`。

限制：只能证明数值关系，不能证明人口数为家庭户/户籍/常住人口。

### S21 [U] 人口准确口径/基准日

人口数、合计、户规模准确统计口径、差值成因、图层采用的普查基准时点未知。

- 包：`（8）西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据.zip`；成员：`西藏日喀则市吉隆县第七次人口普查数据/西藏日喀则市吉隆县第七次人口普查数据.dbf`。
  字段/属性：`人口数`；准确摘录：`16155`。
- 包：`（8）西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据.zip`；成员：`西藏日喀则市吉隆县第七次人口普查数据/西藏日喀则市吉隆县第七次人口普查数据.dbf`。
  字段/属性：`合计`；准确摘录：`17536`。

限制：“第七次人口普查”见包名/成员名，但本地无字典；不能把人口数直接改称家庭户或户籍人口，也不能平均摊到局地栅格。

### S22 [U] RGI日期字段及哨兵定义

BgnDate/EndDate/src_date的精确定义、时间边界、负值哨兵含义未在本地文档给出。

- 包：`（3）日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集 (2000-2020).rar`；成员：`西藏日喀则市吉隆县特大洪水—200km周围内的冰川和冰川厚度变化数据集/RGI_V6_JilongFlood_Buffer_200km.dbf`。
  字段/属性：`DBF字段名`；准确摘录：`BgnDate / EndDate`。
- 包：`（3）日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集 (2000-2020).rar`；成员：`西藏日喀则市吉隆县特大洪水—200km周围内的冰川和冰川厚度变化数据集/文档说明.docx`。
  字段/属性：`word/document.xml`；准确摘录：`Randolph Glacier Inventory 6.0和7.0`。

限制：日期样式和字段名提示日期（I）；旧报告直接称源影像日期过强，需源产品字典。

### S23 [U] 气象QC/时区/降水累计

本地空间附件3—8不能补足气象QC代码、站点时区、降水累计起止/清零/累计方式定义。

- 包：`（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip`；成员：`Glacier topographic and dynamic drivers (Glacier-collapse and debris-flow disasters at Langtang Lirung, Nepal).nc`。
  字段/属性：`global.Conventions`；准确摘录：`CF-1.8`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`eainfo/detailed/attr[flag]/attrlabl`；准确摘录：`flag`。

限制：未找到定义不等于这些规则不存在；仅本次检索范围无依据，气象附件由主代理另审。

### S24 [F] DOCX文档时间

docProps/core.xml created=2026-09-02T12:59:00Z，modified=2026-09-02T13:01:00Z。

- 包：`（3）日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集 (2000-2020).rar`；成员：`西藏日喀则市吉隆县特大洪水—200km周围内的冰川和冰川厚度变化数据集/文档说明.docx`。
  字段/属性：`docProps/core.xml dcterms:created`；准确摘录：`2026-09-02T12:59:00Z`。
- 包：`（3）日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集 (2000-2020).rar`；成员：`西藏日喀则市吉隆县特大洪水—200km周围内的冰川和冰川厚度变化数据集/文档说明.docx`。
  字段/属性：`docProps/core.xml dcterms:modified`；准确摘录：`2026-09-02T13:01:00Z`。

限制：Z只属于DOCX文档属性，不可将UTC扩展到灾害/气象站/XML处理时区。

### S25 [F] PRJ与CPG作用边界

附件3/8的PRJ声明WGS84地理坐标和Degree；附件6声明CGCS2000地理坐标和Degree；现有CPG均写UTF-8。

- 包：`（8）西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据.zip`；成员：`西藏日喀则市吉隆县第七次人口普查数据/西藏日喀则市吉隆县第七次人口普查数据.prj`。
  字段/属性：`WKT`；准确摘录：`UNIT["Degree",0.0174532925199433]`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.prj`。
  字段/属性：`WKT`；准确摘录：`GCS_China_Geodetic_Coordinate_System_2000`。
- 包：`（8）西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据.zip`；成员：`西藏日喀则市吉隆县第七次人口普查数据/西藏日喀则市吉隆县第七次人口普查数据.cpg`。
  字段/属性：`file text`；准确摘录：`UTF-8`。

限制：坐标系统和字符编码不提供时区、事件日期、人口口径或分类定义。附件6没有CPG，不臆造其编码声明。

### S26 [F] 历史XML计数与实体不一致

XML geoObjCnt/efeacnt都记0，而读取实际图层为84条。

- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`spatRepInfo/VectSpatRep/geometObjs/geoObjCnt`；准确摘录：`0`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.shp.xml`。
  字段/属性：`spdoinfo/ptvctinf/esriterm/efeacnt`；准确摘录：`0`。
- 包：`（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip`；成员：`西藏日喀则市吉隆县泥石流灾害区历史灾点数据/西藏日喀则市吉隆县泥石流灾害区历史灾点数据.dbf`。
  字段/属性：`DBF record count`；准确摘录：`84`。

限制：表明自动同步元数据可能不完整；不能仅靠XML摘要认定图层为空，亦不自动推翻其他字段元数据。

## 纠正旧审计用语的建议

- 旧措辞：影像Time确定为影像获取日；解译Time确定为实际解译日。建议：F仅字段名/Date类型/赋值历史及存储值；业务含义仅I，准确获取/作业日U，不作事件日期。（HFIELD_影像Time, HFIELD_解译Time, S12, S13, S14）

- 旧措辞：人口数为户籍/家庭户人口（包括其他整合文字可能的扩写）。建议：只称字段人口数=16155。比值接近户规模为I；口径U。本人旧报告“提示不同统计口径”也应收紧为“数值存在差异，准确口径未知”。（S19, S20, S21）

- 旧措辞：DEM20260826泛称元数据时间，或据其称灾前地形。建议：补充F：lineage明确20260826/171843的Clip操作；时区、输入采集日期和灾前状态U。（S09, S10）

- 旧措辞：RGI日期字段确定为源影像日期。建议：仅字段名/值为事实；日期样式I，业务定义及哨兵U，待原产品字典。（S22）

- 旧措辞：Resolution=1m证明原影像真实分辨率1m。建议：F只确认字符串赋值；真实源影像分辨率/精度未明确。（HPROC_Resolution, S16）

- 旧措辞：dhdt默认m/year，误差默认1σ。建议：F只确认变化率/误差；具体数值单位和误差定义U。（S02, S03）

- 旧措辞：NEAREST代表分类生产/年度配准方法。建议：F仅2020 TIFF金字塔重采样标签；生产/配准方法U。（S18）

## 原始包SHA256

|附件|SHA256|
|---|---|
|3|`c1869251bf7d9b1a8d0b5fb81134ca9ffeacfe26df815959c37af48c37cd96d1`|
|4|`fffd408711bba9c23b1409eef4aa09deec120a3e1fd97600bcbd5868c92d3c13`|
|5|`a9d23370c61485068734c264b876b377934d8b7141f0cc96ca9a58d1e7f7bfdd`|
|6|`38addea9bf18e7c5cd05413901f5ea2921556aff6c4b74215e582e1fcb3469d7`|
|7|`06b6cc274c680a9e611e63d6610d66dc97ad2d3fdd669fdbcd0556be0bba02a2`|
|8|`21c2a1c4485bbfdecb05a4d09063cbc644a2dfb3804797da18c89575dbd680e7`|

## 复核范围及可复查材料

共193个源成员登记。全部原始包重新计算SHA256；所有文本元数据、NetCDF与DBF直接从原始ZIP/RAR提取字节，与现有解压副本SHA256一致。RAR TIFF本次只校验原始成员路径、原包SHA256和解压成员SHA256，没有逐个重新解压，JSON逐项明确此验证边界。ZIP TIFF已直接比对原始成员。

核对173个TIFF的全部可用元数据命名空间与波段单位、3个外置XML（附件6 shp.xml、附件7 XML/aux.xml）、全部PRJ/CPG/TFW、1个DOCX全部word/*.xml与docProps/*.xml、NetCDF13个变量与全部全局属性（decode_cf=False，含_FillValue）。GDAL运行时生成的DERIVED_SUBDATASETS域不作为源文件事实。

JSON另列每一个DBF头更新日期、ZIP成员封装时间、历史完整处理历史及各字段XML子项。封装时间无时区，不作采集时间；DBF更新日期不作灾害日期。

附件6 XML只有FID/Shape的Esri attrdef；影像Time、解译Time、flag、Resolution、类型等未附业务定义。处理日志可能承继上游完整图层，不能保证每次赋值作用于当前84条子集。

本次没有补充事件时间、降水累计规则、质量合格标志或缺失值。最终预测标签与关键降水特征应继续暂缓，直到对应官方定义核实。

验证补记：原始6个压缩包SHA256与前次审计完全一致。每条引文附成员与原包SHA256；所有普通原文引文均匹配实际元数据文本/属性值，结构化字段/数值呈现另标注，并未冒充文档原句。JSON可解析，证据分级计数为F44/I2/U9。
