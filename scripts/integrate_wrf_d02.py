"""Lightweight, read-only integration of the existing D02 audit; no model reruns.

Run from any directory: python scripts/integrate_wrf_d02.py
All deliverable paths and provenance paths are project-relative.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import html
import json
import platform
import subprocess
import sys

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from question4_visuals import save_multi_panel

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'output/wrf_d02_review'
OUT = ROOT / 'output/wrf_d02_integration'
END = '2026-08-26T10:00:00+08:00'
INPUTS = ['site_timeseries.csv', 'site_grid_comparison.csv', 'event_comparison.csv',
          'rain_5km_neighborhood.csv', 'metadata.json', 'variable_inventory.csv']


def aware_time(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError('Explicit timezone required')
    return t.tz_convert('Asia/Shanghai')


def context_kind(end):
    return 'pre_event_complete' if aware_time(end) <= aware_time(END) else 'cross_event'


def window_values(frame, end, hours):
    """Accumulated rain differences; temperature means of N hourly endpoint samples.

    Temperature mean is explicitly NOT a continuous-time average. Missing
    temperature stays missing; missing/reset rain cannot be silently integrated.
    """
    end = aware_time(end)
    start = end - pd.Timedelta(hours=hours)
    f = frame.copy()
    f.index = pd.DatetimeIndex([aware_time(t) for t in f.time_beijing])
    if f.index.has_duplicates:
        raise ValueError('Duplicate timestamps')
    expected = pd.date_range(start, end, freq='h')
    if not expected.isin(f.index).all():
        raise ValueError('Incomplete hourly window')
    selected = f.loc[expected]
    rain = selected.rain_accum_mm.to_numpy(float)
    if not np.isfinite(rain).all() or (np.diff(rain) < 0).any():
        raise ValueError('Missing or resetting cumulative rainfall')
    total = float(rain[-1] - rain[0])
    recorded = selected.rain_increment_mm.iloc[1:].to_numpy(float)
    if not np.isfinite(recorded).all() or not np.allclose(recorded, np.diff(rain), atol=1e-10, rtol=1e-10):
        raise ValueError('Audit increments disagree with cumulative differences')
    temps = selected.T2_C.iloc[1:].to_numpy(float)
    return dict(start_beijing=start.isoformat(), end_beijing=end.isoformat(),
                start_utc=start.tz_convert('UTC').isoformat(), end_utc=end.tz_convert('UTC').isoformat(),
                window_hours=hours, sample_count=len(temps), context=context_kind(end), rain_mm=total,
                rain_increment_sum_mm=float(recorded.sum()), T2_end_C=float(temps[-1]),
                T2_sample_mean_C=float(np.mean(temps)), T2_sample_min_C=float(np.min(temps)),
                T2_sample_max_C=float(np.max(temps)))


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def csv(frame, name):
    frame.to_csv(OUT / name, index=False, encoding='utf-8-sig', float_format='%.17g')


def md(name, content):
    (OUT / name).write_text(content.strip() + '\n', encoding='utf-8')


def frozen_files():
    paths = []
    for folder in ['output/question1', 'output/question2/final', 'output/question3/final', 'output/question4/final', 'docs', 'config', 'scripts']:
        paths.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    return {relative(p): sha(p) for p in sorted(set(paths))}


def categorical_panels(path, panels):
    """Grouped bars avoid suggesting a continuous source-to-port spatial gradient."""
    im = Image.new('RGB', (1800, 1100), 'white')
    draw = ImageDraw.Draw(im)
    font, small = ImageFont.load_default(size=19), ImageFont.load_default(size=16)
    for n, panel in enumerate(panels):
        left, top = (n % 2) * 900, (n // 2) * 550
        x0, x1, y0, y1 = left + 85, left + 870, top + 85, top + 475
        ymax = max(float(max(curve[2])) for curve in panel['series']) * 1.18
        ymax = ymax if ymax > 0 else 1
        draw.text((left + 15, top + 12), panel['title'], font=font, fill='#17293d')
        draw.text((left + 15, top + 44), panel['y_label'], font=small, fill='#17293d')
        for i in range(5):
            v = ymax * i / 4
            yy = y1 - (y1-y0) * i/4
            draw.line((x0, yy, x1, yy), fill='#dce2e9')
            draw.text((left + 10, yy-8), f'{v:.3g}', font=small, fill='#334155')
        for j, label in enumerate(['Source A/B', 'Port']):
            center = x0 + (j + .5) * (x1-x0)/2
            draw.text((center-50, y1+10), label, font=font, fill='#17293d')
            for k, (domain, _, values, color) in enumerate(panel['series']):
                value = float(np.asarray(values)[j])
                xx = center - 85 + k*90
                yy = y1 - value/ymax * (y1-y0)
                draw.rectangle((xx, yy, xx+70, y1), fill=color)
                draw.text((xx, yy-22), f'{value:.4g}', font=small, fill=color)
                draw.text((xx, y1+36), domain, font=small, fill=color)
    im.save(path)


def mark_event_hour(path):
    """Shade only the known 10:00--11:00 clock interval, not a trigger estimate."""
    with Image.open(path) as original:
        im = original.convert('RGBA')
    overlay = Image.new('RGBA', im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default(size=13)
    for n in range(4):
        left, top = n % 2 * 900, n // 2 * 550
        x0, x1 = left + 74, left + 881
        start, end = x0 + 24/26*(x1-x0), x0 + 25/26*(x1-x0)
        draw.rectangle((start, top+40, end, top+496), fill=(255, 194, 66, 45))
        draw.line((start, top+40, start, top+496), fill='#8b6515')
        draw.line((end, top+40, end, top+496), fill='#8b6515')
        draw.text((start-34, top+45), '10:00', font=font, fill='#6e500d')
        draw.text((end-10, top+65), '11:00', font=font, fill='#6e500d')
    Image.alpha_composite(im, overlay).convert('RGB').save(path)


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    frozen = frozen_files()
    series = pd.read_csv(INPUT / 'site_timeseries.csv')
    grid = pd.read_csv(INPUT / 'site_grid_comparison.csv')
    event = pd.read_csv(INPUT / 'event_comparison.csv')
    nearby = pd.read_csv(INPUT / 'rain_5km_neighborhood.csv')
    metadata = json.loads((INPUT / 'metadata.json').read_text(encoding='utf-8'))
    inventory = pd.read_csv(INPUT / 'variable_inventory.csv')
    checks = []

    def check(name, passed, detail=''):
        checks.append(dict(check=name, passed=bool(passed), detail=detail))
        if not passed:
            raise AssertionError(f'{name}: {detail}')

    check('UTC_BJT_same_instant', all(aware_time(a) == aware_time(b) for a, b in zip(series.time_utc, series.time_beijing)))
    check('temperature_K_to_C', np.allclose(series.T2 - 273.15, series.T2_C, atol=1e-10))
    check('rain_RAINC_plus_RAINNC', np.allclose(series.RAINC + series.RAINNC, series.rain_accum_mm, atol=1e-10))
    expected_units = {'RAINC': 'mm', 'RAINNC': 'mm', 'T2': 'K', 'TSK': 'K', 'PSFC': 'Pa', 'SNOW': 'kg m-2',
                      'SNOWH': 'm', 'ACSNOM': 'kg m-2', 'SFROFF': 'mm', 'UDROFF': 'mm', 'SMOIS': 'm3 m-3', 'TSLB': 'K'}
    for domain in ['d01', 'd02']:
        inv = inventory[inventory.domain == domain].set_index('name')
        for var, unit in expected_units.items():
            check(f'{domain}_{var}_unit', inv.loc[var, 'unit'] == unit, unit)
        a = metadata[domain]['attributes']
        check(f'{domain}_cadence_1h', metadata[domain]['time_steps_seconds'] == [3600.0])
        check(f'{domain}_RAINSH_not_added', (series.loc[series.domain == domain, 'RAINSH'] == 0).all() and a['SHCU_PHYSICS'] == 0)
        g = grid[(grid.domain == domain) & grid.site.isin(['source_A', 'source_B'])]
        check(f'{domain}_AB_same_grid', len(g[['row', 'col']].drop_duplicates()) == 1)
    check('D01_D02_nesting', metadata['d02']['attributes']['PARENT_ID'] == metadata['d01']['attributes']['GRID_ID'])

    windows, water = [], []
    for (domain, site), f in series.groupby(['domain', 'site']):
        check(f'{domain}_{site}_full_cadence', len(f) == 73 and (pd.to_datetime(f.time_utc).diff().iloc[1:] == pd.Timedelta(hours=1)).all())
        for hours, end in [(h, END) for h in [1, 6, 12, 24]] + [(1, '2026-08-26T11:00:00+08:00')]:
            d = dict(domain=domain, site=site, **window_values(f, end, hours))
            d['spinup_at_window_start_h'] = (aware_time(d['start_beijing']) - aware_time(metadata[domain]['first_utc'])).total_seconds() / 3600
            d['evidence'] = 'WRF_model_output_not_observation'
            windows.append(d)
            prior = event[(event.domain == domain) & (event.site == site) & (event.end_hour_beijing == aware_time(end).hour)].iloc[0]
            col = {1: 'rain_previous_hour_mm', 6: 'rain_previous_6h_mm', 24: 'rain_previous_24h_mm'}.get(hours)
            if col:
                check(f'audit_agreement_{domain}_{site}_{hours}_{aware_time(end).hour}', np.isclose(d['rain_mm'], prior[col], atol=1e-10, rtol=1e-10))
            ix = f.set_index(pd.DatetimeIndex([aware_time(t) for t in f.time_beijing]))
            first, last = ix.loc[aware_time(d['start_beijing'])], ix.loc[aware_time(end)]
            w = dict(d)
            for var, unit in [('ACSNOM', 'kg_m2'), ('SFROFF', 'mm'), ('UDROFF', 'mm')]:
                values = ix.loc[aware_time(d['start_beijing']):aware_time(end), var].to_numpy(float)
                check(f'{domain}_{site}_{hours}_{aware_time(end).hour}_{var}_no_reset', np.isfinite(values).all() and (np.diff(values) >= -1e-10).all())
                w[f'{var}_increment_{unit}'] = float(last[var] - first[var])
            w.update(TSK_end_C=float(last.TSK - 273.15), PSFC_end_Pa=float(last.PSFC),
                     SNOW_end_kg_m2=float(last.SNOW), SNOWH_end_m=float(last.SNOWH),
                     SMOIS_top_end_m3_m3=float(prior.soil_moisture_top_m3_m3),
                     TSLB_top_end_C=float(prior.soil_temp_top_K - 273.15),
                     SH2O_top_end_m3_m3=np.nan, local_water_availability=np.nan,
                     missing_reason='SH2O_not_in_lightweight_export;local_glacier_water_unobserved',
                     critical_threshold_evaluated=False, trigger_probability=np.nan)
            water.append(w)
    windows, water = pd.DataFrame(windows), pd.DataFrame(water)
    csv(windows, 'q1_weather_windows.csv')
    csv(water, 'q2_hydrothermal_scenarios.csv')
    keys = ['site', 'window_hours', 'context', 'start_beijing', 'end_beijing']
    numeric = ['rain_mm', 'T2_end_C', 'T2_sample_mean_C', 'SFROFF_increment_mm', 'UDROFF_increment_mm', 'SMOIS_top_end_m3_m3', 'TSLB_top_end_C']
    diff = water[water.domain == 'd01'][keys + numeric].merge(water[water.domain == 'd02'][keys + numeric], on=keys, suffixes=('_d01', '_d02'))
    for name in numeric:
        diff[name + '_d02_minus_d01'] = diff[name + '_d02'] - diff[name + '_d01']
    diff['comparison_type'] = 'nested_grid_scale_context_not_independent_models_or_trigger_score'
    csv(diff, 'q2_d02_minus_d01.csv')

    nearby['start_beijing'] = nearby.end_hour_beijing.map(lambda h: f'2026-08-26T{h-1:02d}:00:00+08:00')
    nearby['end_beijing'] = nearby.end_hour_beijing.map(lambda h: f'2026-08-26T{h:02d}:00:00+08:00')
    nearby['statistic'] = 'unweighted_grid_centers_within_5000m_not_basin_area_mean'
    nearby['context'] = nearby.end_beijing.map(context_kind)
    check('empty_neighborhood_not_zero', nearby.loc[nearby.grid_centers == 0, ['rain_increment_min_mm', 'rain_increment_max_mm', 'rain_increment_mean_mm']].isna().all().all())
    csv(nearby, 'q2_5km_neighborhood.csv')
    csv(grid, 'grid_location_evidence.csv')
    reliability = grid.copy()
    reliability['nominal_DX_m'] = reliability.domain.map({k: v['attributes']['DX'] for k, v in metadata.items()})
    reliability['time_step_s'] = 3600
    reliability['initialization_utc'] = reliability.domain.map({k: v['first_utc'] for k, v in metadata.items()})
    for col in ['model_generation_time', 'public_availability_time', 'empirical_95pct_coverage', 'physical_trigger_seconds']:
        reliability[col] = None
    reliability['meteorological_AB_independent'] = False
    reliability['evidence_kind'] = 'retrospective_model_context;no_proven_operational_availability'
    csv(reliability, 'q3_reliability.csv')

    # Record every rendered ordinate/abscissa; figures never contain invented values.
    points = []
    def record(fig, panel, label, x, y, x_unit, y_unit):
        for xx, yy in zip(x, y):
            points.append(dict(figure=fig, panel=panel, series=label, x=float(xx), y=float(yy), x_unit=x_unit, y_unit=y_unit))
    colors = {'d01': '#dc2626', 'd02': '#2563eb'}
    panels = []
    for site, title in [('source_A', 'Source A/B (one shared grid per domain)'), ('port', 'Port nearest grid')]:
        for var, unit in [('rain_increment_mm', 'Hourly rainfall (mm)'), ('T2_C', '2 m temperature (deg C)')]:
            curves = []
            for domain in ['d01', 'd02']:
                f = series[(series.domain == domain) & (series.site == site)].copy()
                f['hours'] = [(aware_time(t) - aware_time(END)).total_seconds()/3600 for t in f.time_beijing]
                f = f[(f.hours >= -24) & (f.hours <= 2)]
                x, y = f.hours.to_numpy(float), f[var].to_numpy(float)
                # Rain is a staircase over its actual hourly support, not an interpolated rain rate.
                if var == 'rain_increment_mm':
                    f = f[f.hours > -24]
                    x = np.column_stack([f.hours.to_numpy()-1, f.hours.to_numpy()]).ravel()
                    y = np.repeat(f[var].to_numpy(), 2)
                curves.append((domain.upper(), x, y, colors[domain]))
                record('q1_weather_comparison.png', title + ' / ' + var, domain, x, y, 'hours since 2026-08-26 10:00 BJT', unit)
            panel = dict(title=title, x_label='Hours from Aug 26 10:00 BJT', y_label=unit, series=curves, xlim=(-24, 2))
            if var == 'rain_increment_mm':
                panel['ylim'] = (0, max(float(max(c[2])) for c in curves)*1.1)
            panels.append(panel)
    save_multi_panel(OUT / 'q1_weather_comparison.png', panels, cols=2, size=(1800, 1100))
    mark_event_hour(OUT / 'q1_weather_comparison.png')
    panels = []
    for site in ['source_A', 'port']:
        curves = []
        for domain in ['d01', 'd02']:
            f = windows[(windows.domain == domain) & (windows.site == site) & (windows.context == 'pre_event_complete')].sort_values('window_hours')
            curves.append((domain.upper(), f.window_hours, f.rain_mm, colors[domain]))
            record('q1_antecedent_windows.png', site, domain, f.window_hours, f.rain_mm, 'window hours ending 10:00 BJT', 'mm')
        label = 'Source A/B' if site == 'source_A' else 'Port'
        panels.append(dict(title=label + ': rainfall before 10:00 BJT', x_label='Window length (h)', y_label='Accumulated rain (mm)', series=curves,
                           xlim=(0, 24), ylim=(0, max(float(max(c[2])) for c in curves)*1.1)))
    save_multi_panel(OUT / 'q1_antecedent_windows.png', panels, cols=2, size=(1800, 650))
    q2panels = []
    for var, unit, title in [('T2_end_C', 'deg C', '2 m temperature at 10:00 BJT'),
                            ('SMOIS_top_end_m3_m3', 'm3/m3', 'Top-layer model soil moisture at 10:00 BJT'),
                            ('SFROFF_increment_mm', 'mm in preceding 24 h', 'Model surface runoff ending 10:00 BJT'),
                            ('UDROFF_increment_mm', 'mm in preceding 24 h', 'Model underground runoff ending 10:00 BJT')]:
        curves = []
        for domain in ['d01', 'd02']:
            f = water[(water.domain == domain) & (water.window_hours == 24) & water.site.isin(['source_A', 'port'])].set_index('site').loc[['source_A', 'port']]
            curves.append((domain.upper(), [0, 1], f[var], colors[domain]))
            record('q2_hydrothermal_comparison.png', var, domain, [0, 1], f[var], '0=source A/B;1=port (categories)', unit)
        q2panels.append(dict(title=title, y_label=unit, series=curves))
    categorical_panels(OUT / 'q2_hydrothermal_comparison.png', q2panels)
    csv(pd.DataFrame(points), 'figure_numeric_sources.csv')
    for p in OUT.glob('*.png'):
        with Image.open(p) as im:
            im.verify()

    conflicts = []
    for filename, needle, kind, suggestion in [
        ('docs/question1-v1.md', '待WRF/GFS补齐', '历史阶段范围，当前已补充', '保留原版本；新增本附录，说明已获得D01/D02天气背景。'),
        ('docs/question1-v1.md', 'd02文件仍缺', '数据可用性已过时', 'D02现已审计并可用；源区局地实测仍缺。'),
        ('docs/question1-v1.md', '本地无雨记录', '空间表述需限定，不是原始数值错误', '改写建议：塔站61个标签记录为零，区间语义未确认；不能外推到整个源区或全部灾前窗口。'),
        ('docs/question2-v1.md', '约9.014 km', '新增尺度对照，保留D01事实', '增加D02约3.005km、小时输出；不改变临界阈值与未知水源。'),
        ('docs/question3-v1.md', '约9.014 km', '新增尺度对照，原可预报性结论保留', '补充D02源点距离742/465m；生成和公开可得时间仍未知。'),
    ]:
        for n, line in enumerate((ROOT / filename).read_text(encoding='utf-8').splitlines(), 1):
            if needle in line:
                conflicts.append(dict(path=filename, line=n, original_excerpt=line, classification=kind, appendix_suggestion=suggestion, original_modified=False))
    conflicts.append(dict(path='docs/question1-v1.md;docs/question2-v1.md;docs/question3-v1.md', line='', original_excerpt='未检出“整个源区灾前无雨”这一原句', classification='禁止泛化而非指控原报告错误', appendix_suggestion='10:00前最后小时源区最近格点为0，不代表前24小时为0，也不代表5km全部格点无雨。', original_modified=False))
    csv(pd.DataFrame(conflicts), 'conclusion_conflicts.csv')
    adopted = [
        ('Q1', 'D01/D02前1/6/12/24h降水及温度', '采用为模式背景附录', '原五因素排名、因果排序均未改变'),
        ('Q2', 'D02格点水热、土壤和径流描述及D02-D01差', '采用描述性动态情景', '不计算新的阈值判别、评分或触发概率'),
        ('Q2', 'SH2O液态土壤水', '未采用：原始变量存在，但轻量审计未导出点序列', '保持空值；SMOIS不可冒充SH2O'),
        ('Q2', '真实冰川融水、沟道水源可用性', '未采用：未观测，SNOW/ACSNOM零值不解决缺口', '保持未知；不填0或1'),
        ('Q3', '3km空间尺度及A/B格点距离', '采用可靠性附录', '未改时间区间、提前量或95%覆盖率状态'),
        ('Q4', '模式降水和陆面径流', '仅补充局限说明', '未改入流、摩擦、DEM、方程或仿真结果'),
    ]
    csv(pd.DataFrame(adopted, columns=['question', 'information', 'adoption', 'unchanged_or_reason']), 'adoption_decisions.csv')

    source = windows[(windows.site == 'source_A') & (windows.context == 'pre_event_complete')].pivot(index='window_hours', columns='domain', values='rain_mm')
    t2 = water[(water.site == 'source_A') & (water.window_hours == 24)].set_index('domain')
    report = f'''# WRF D02截止前轻量补充（独立附录）

## 使用范围与主要结果
所有数字来自已审计的WRF模式输出，不是现场观测。D01与D02是同一嵌套模式系统的尺度对照，不是两个独立预报模型。原四问的模型、参数、评分、排序、时间区间及仿真结果均不改变。

源区A/B在各自域内共用一个最近格点。以下窗口统一截至2026-08-26 10:00北京时间（02:00 UTC），不是截至10:54:19的精确前N小时：

| 完整小时窗口 | D01源区降水 mm | D02源区降水 mm | 窗口起点距模式初始化 |
|---|---:|---:|---:|
| 09:00—10:00（1h） | {source.loc[1,'d01']:.6f} | {source.loc[1,'d02']:.6f} | 25h |
| 04:00—10:00（6h） | {source.loc[6,'d01']:.6f} | {source.loc[6,'d02']:.6f} | 20h |
| 前日22:00—当日10:00（12h） | {source.loc[12,'d01']:.6f} | {source.loc[12,'d02']:.6f} | 14h |
| 前日10:00—当日10:00（24h） | {source.loc[24,'d01']:.6f} | {source.loc[24,'d02']:.6f} | 2h |

24小时窗口起点距模式启动仅2小时，启动调整影响未被独立评估；不能把24h值当作已验证的源区真实累计雨量。6/12h窗口也不是已证明不受启动影响。
09:00—10:00源区最近格点两域均为零，但D02源区5km内9个格点的该小时最大值约0.000916mm，故“全部邻域严格无雨”亦不成立。
10:00—11:00覆盖所报告10:52冰崩起始、10:54:19—10:55:10转化阶段及10:59到达；此时段已单列为cross_event，不能用作事件前完整小时特征。

10:00源区D01/D02的T2分别为{t2.loc['d01','T2_end_C']:.3f} / {t2.loc['d02','T2_end_C']:.3f}℃。
对应模式地形约4108/4936m，口岸格点约3022/2593m（报告口岸高程约1800m）。差异混有格点地形和地表表示差异，不能解释为相同真实海拔的温度误差或精度提升。

## Q1附录与冲突处理
保留原五因素排名。D02新增的是“前期水热背景与临灾前完整小时不同”的描述证据，不能由单次嵌套尺度差异推断真实降雨致灾。
旧报告D02缺失的表述已过时；原D01数值未因此失效。原报告塔站61个标签零值必须限定为塔站记录，不能外推成整个跨境源区灾前无雨。
检查Q1/Q2/Q3 v1正文未检出“整个源区灾前无雨”原句；conclusion_conflicts.csv列明原文定位、表述风险和追加修订建议，没有改写原文件。

## Q2描述性水热情景（不触发重新评分）
q2_hydrothermal_scenarios.csv给出前1/6/12/24h雨量、T2端点及小时端点样本均值/极值、TSK、PSFC、SNOW、SNOWH、ACSNOM、SFROFF、UDROFF、表层SMOIS与TSLB。
T2均值使用(start,end]的N个小时端点样本，不是连续时间积分。土壤仅有10:00/11:00端点，不是各窗口土壤均值。
降水使用Δ(RAINC+RAINNC)，浅对流RAINSH审计为0且SHCU_PHYSICS=0；逐小时差分和端点累计差相互核对。ACSNOM/SFROFF/UDROFF也只以累计差描述模式融雪/地表/地下径流量。
SFROFF/UDROFF单位mm，不是沟道流量m³/s；没有真实汇水面积与路由，不能转换为第四问入流。
SMOIS按元数据为土壤含水量，不能当作单独液态水SH2O或冰川液态水。SH2O原始文件有变量，但轻量审计未导出点值，本次保留缺失；没有重读大文件。
源区D02土地利用类别7不同于元数据冰雪类15；SNOW/SNOWH/ACSNOM零值只能描述该模式格点，不支持“真实冰川无雪/无融水”。
本地水源可用性、触发概率保持缺失。不能将格点SMOIS与第二问异地实验阈值直接比较，不能把格点土壤水分替代坡体含水条件。
因此只生成水热描述情景和D02-D01差异表，不计算新的物理临界判别、权重评分或触发概率；原Q2评估结论保持。

## 邻域与代表性
5km邻域是格点中心落在圆内的无权统计，未按格点面积或真实流域相交面积加权；不是流域面积平均。
D02源区A/B各9点、口岸12点；D01源区1点，口岸0点，其统计保留为空，绝不填零。A/B圆内统计恰相同也不等于独立气象信息。
现有邻域轻量导出只覆盖09—10和10—11两个小时，无法据此构造6/12/24h邻域累计。本版没有假装补齐。

## Q3空间与时间可靠性附录
名义网格从D01约9.014km细化到D02约3.005km，源点A/B至最近D02格点分别742.150m/464.592m，口岸约1999.300m。较近采样改善空间匹配，不等于有独立验证的预报精度提高。
输出仍逐小时；51秒转化阶段远短于3600秒输出步长。没有分钟/秒级物理触发观测。
初始化为2026-08-25 00:00 UTC（08:00北京时间）；有效时刻为文件Times。实际运行生成、历史公开可得时间和真实预警签发时间仍未知，本地下载时间不能替代。
不能把回溯WRF场称为已证实的灾前业务预报；不能以插值生成秒级标签。本次未计算任何95%区间；缺独立触发标签，经验覆盖率仍不可估计。既有条件传播情景和校准/验证限制均保留。

## Q4局限补充
D02不能直接提供冰岩崩释放体积、释放历时、真实融水过程或沟道入流边界。本次未改第四问方程、地形、体积、沟宽、摩擦或任何仿真结果。
'''
    md('scientific_appendix.md', report)
    md('q3_reliability_appendix.md', '# 第三问D02可靠性补充\n\n' + report.split('## Q3空间与时间可靠性附录\n')[1].split('## Q4')[0])
    md('B_C_brief.md', f'''# B审核与C论文引用简表

## C可引用的短段落（需同时引用数据来源）
WRF嵌套域对照显示，在2026年8月26日北京时间10:00之前的24个完整小时内，源区最近格点D01与D02累计降水分别为{source.loc[24,'d01']:.2f}mm和{source.loc[24,'d02']:.2f}mm；对应前6/12h值见数值表。最后一个完整小时09:00—10:00两域均为0mm。这表明模式表示的前期降水背景与临灾前该小时不同，不能概括为“源区灾前始终无雨”。24小时窗口从模式启动后仅2小时开始，启动调整影响尚未验证。D02将名义网格细化至约3km，源点A/B距最近格点约742m和465m，但两点共用同一格点，仍为小时尺度模式背景，不能支持秒级触发预报或经验95%覆盖率估计。

## C不能写
- “D02实测降雨26.09mm导致了本次泥石流”或“D02预报更准确”。
- “两个独立模型验证了因果关系”“A/B两站独立证明”。
- “SNOW=0，所以真实冰川无融水”；“SMOIS越过本地实测临界值”。
- “10—11小时为灾前雨量”；“95%区间/覆盖率已经验证”。
- “D02径流即第四问沟道入流”；“D02解决了业务预报发布时间缺口”。

## B逐项复核（待人工签字）
1. 用q1_weather_windows.csv复核24h/12h/6h/1h端点；24h起点为前日10:00，启动后2h，非精确事件前24h。
2. 对照q1_weather_windows.csv和q2_hydrothermal_scenarios.csv的rain_mm，确认各行一致，10—11单列cross_event。
3. 对照grid_location_evidence.csv确认A/B共格点、D02口岸地形仍偏高；不能把更近采样当作已验证准确率。
4. q2_5km_neighborhood.csv中D01口岸0个格点的统计必须为空；邻域均值不等于流域面积平均。
5. 核对SH2O、local_water_availability和trigger_probability空值，原阈值、排名和模型参数未改变。
6. 核对原文件保护清单及verification.json；自动验证通过不等于降雨场已通过独立观测验证。
7. 出版/竞赛引用仍应沿用原数据来源页与许可，不将本附录当作新的原始数据发布授权。

## 图注（均来自模式计算，非观测）
- q1_weather_comparison.png：横轴为相对8月26日10:00北京时间的小时数；降水纵轴为每小时累计mm（阶梯表示区间），气温为2m温度℃（连线仅引导读图）。源区/口岸并列；黄色带x=0到1是10—11跨事件小时，不能用于灾前标签。说明模式时空差异，不能证明真实致灾因果。
- q1_antecedent_windows.png：横轴为截至10:00的完整窗口长度h，纵轴累计mm；只在1/6/12/24h有计算，连线不代表其他窗口已经计算。支持窗口敏感性，不是置信区间。
- q2_hydrothermal_comparison.png：横轴分源区A/B、口岸两组，每组两根柱分别为D01/D02；数值来源表以0/1编码这两个位置类别，不是连续距离。纵轴分别T2℃、SMOIS m³/m³、前24h地表/地下模式径流mm。不能说明沿程变化、真实冰川融水或沟道流量。
''')
    md('data_dictionary.md', '''# 字段、单位与复算口径

q1_weather_windows与q2_hydrothermal_scenarios：每行=域×点×窗口；A/B行用于点位追溯，不算独立样本。
start/end_beijing含+08:00；start/end_utc含+00:00；window_hours与spinup_at_window_start_h单位h。
rain_mm=累计RAINC+RAINNC在end减start；rain_increment_sum_mm=相同区间逐小时差之和。
T2_end_C=end时刻值；T2_sample_mean/min/max_C=(start,end]小时端点N个样本的统计；sample_count=N。
TSK_end_C为模式地表温度，PSFC_end_Pa为表面气压，均为end值。
SNOW_end_kg_m2=模式雪水当量，SNOWH_end_m=模式雪深；不等同真实冰川储水。
ACSNOM_increment_kg_m2=累计模式融雪量端点差；SFROFF/UDROFF_increment_mm=地表/地下累计模式径流端点差。
SMOIS_top_end_m3_m3为模式最上层土壤水，TSLB_top_end_C为该层温度（K-273.15）；没有假定层厚。
SH2O_top_end_m3_m3缺失（未导出）；local_water_availability缺失（未观测）；trigger_probability缺失（未构建）。
critical_threshold_evaluated=False表示没有利用这些背景数字计算触发临界判别。
q2_d02_minus_d01：差=同点同窗口D02减D01，不是预测误差、观测偏差或概率变化。
figure_numeric_sources：逐个绘图顶点及坐标单位，雨量阶梯的相邻端点重复是区间画法，不是新观测。
CSV采用UTF-8 BOM，空单元格代表缺失，不代表零；17位有效数字用于保留导入浮点值。
''')

    # Browser-readable brief with actual tables; no Office/Python needed to review it.
    browser = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>D02补充审阅</title><style>body{max-width:1150px;margin:40px auto;font:17px/1.7 sans-serif;color:#17293d}pre{white-space:pre-wrap;font:inherit}img{width:100%}table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #ccc;padding:7px}h1,h2{color:#174b7a}</style><h1>D02独立补充审阅</h1>'
    browser += '<pre>' + html.escape(report) + '</pre>'
    for name in ['q1_weather_comparison.png', 'q1_antecedent_windows.png', 'q2_hydrothermal_comparison.png']:
        browser += f'<h2>{name}</h2><img src="{name}" alt="{name}">'
    browser += '<h2>数值摘要</h2>' + windows[['domain', 'site', 'start_beijing', 'end_beijing', 'window_hours', 'rain_mm', 'T2_end_C']].to_html(index=False)
    browser += '<pre>' + html.escape((OUT / 'B_C_brief.md').read_text(encoding='utf-8')) + '</pre></html>'
    (OUT / 'review.html').write_text(browser, encoding='utf-8')
    md('README.md', '''# WRF D02轻量成果补充

先用浏览器打开review.html看正文、图片、数值表和B/C材料；也可直接阅读scientific_appendix.md。原四问输出不变，本目录是追加附录。

## 文件导航
- q1_weather_comparison.png、q1_antecedent_windows.png：源区/口岸逐小时天气与1/6/12/24h窗口对照。
- q1_weather_windows.csv：窗口起止、雨量、温度及启动间隔；figure_numeric_sources.csv为全部图件实际绘图顶点。
- q2_hydrothermal_scenarios.csv、q2_d02_minus_d01.csv：动态水热描述与嵌套域差异，不重新评分。
- q2_5km_neighborhood.csv、q2_hydrothermal_comparison.png：邻域统计与陆面背景，非流域平均或真实入流。
- grid_location_evidence.csv、q3_reliability.csv、q3_reliability_appendix.md：点位和可靠性补充，未知时间留空。
- conclusion_conflicts.csv、adoption_decisions.csv：原文定位、追加修订建议与采用边界。
- B_C_brief.md：人工审核要点、可引用短段及图注；data_dictionary.md：单位与统计定义。
- provenance.json、input_manifest.csv、metadata_snapshot.json：输入路径、SHA256、代码版本与原审计元数据。
- frozen_files_verification.csv、verification.json、test_run.log：原文件保护与实际检查结果。
- artifact_manifest.csv：本次交付文件大小与SHA256（不含清单本身）。

## 复现
在项目根目录激活原mc-base环境后运行：
```powershell
python scripts/integrate_wrf_d02.py
```
入口只读取output/wrf_d02_review/现有六个轻量审计文件与相关正文，不需要再次打开原始3GB D02。依赖沿用项目pandas/numpy/Pillow及绘图工具shapely；版本记录见provenance.json。
复现的前提是已有完整审计文件；原始WRF的SHA256沿用审计记录，本次不重复全文件哈希或重新审计。脚本自动运行本次新增专项测试，保存完整日志；不重新运行四问模型或第四问收敛实验。
所有路径为项目相对路径。Git提交号只是工作区起点；同时记录新脚本/测试/绘图依赖的内容SHA256。未提交、未推送GitHub。
''')

    # Actual test execution and full log, using this interpreter, no existing model tests rerun.
    command = ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_wrf_d02_integration.py', '-v']
    test_start = datetime.now(timezone.utc).isoformat()
    proc = subprocess.run([sys.executable] + command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    test_end = datetime.now(timezone.utc).isoformat()
    md('test_run.log', f'UTC start: {test_start}\nCommand: python {" ".join(command)}\nPython: {platform.python_version()}\n{proc.stdout}{proc.stderr}\nUTC end: {test_end}\nExit code: {proc.returncode}')
    check('unit_test_exit', proc.returncode == 0)
    after = frozen_files()
    check('frozen_content_unchanged', frozen == after, f'{len(frozen)} files including original outputs, docs, config and scripts')
    csv(pd.DataFrame([dict(path=p, before_sha256=s, after_sha256=after.get(p), unchanged=s == after.get(p)) for p, s in frozen.items()]), 'frozen_files_verification.csv')
    hashes = [dict(path=relative(INPUT / p), sha256=sha(INPUT / p), bytes=(INPUT / p).stat().st_size) for p in INPUTS]
    csv(pd.DataFrame(hashes), 'input_manifest.csv')
    (OUT / 'metadata_snapshot.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
    codepaths = [Path(__file__), ROOT/'tests/test_wrf_d02_integration.py', ROOT/'scripts/question4_visuals.py', ROOT/'scripts/review_wrf_d02.py']
    provenance = dict(start_utc=started, finish_utc=datetime.now(timezone.utc).isoformat(),
                      git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                      working_tree_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
                      code_sha256={relative(p): sha(p) for p in codepaths}, input_files=hashes,
                      python=platform.python_version(), pandas=pd.__version__, numpy=np.__version__,
                      pillow=Image.__version__, environment_name='mc-base',
                      command='python scripts/integrate_wrf_d02.py', timezone='Asia/Shanghai (UTC+8)',
                      raw_sha_status='inherited_from_existing_audit_not_rehashed_this_run',
                      tests_command='python ' + ' '.join(command), model_recomputed=False, github_push=False)
    (OUT / 'provenance.json').write_text(json.dumps(provenance, indent=2, ensure_ascii=False), encoding='utf-8')
    for p in OUT.glob('*.csv'):
        pd.read_csv(p)
    check('all_csv_readable', True)
    check('window_table_roundtrip', np.allclose(pd.read_csv(OUT/'q1_weather_windows.csv').rain_mm, windows.rain_mm, atol=1e-12))
    check('Q1_Q2_rain_same', np.array_equal(windows.rain_mm.to_numpy(), water.rain_mm.to_numpy()))
    check('plot_numbers_roundtrip', np.allclose(pd.read_csv(OUT/'figure_numeric_sources.csv').y, [p['y'] for p in points], atol=1e-12))
    check('window_count_30', len(windows) == 30 and len(water) == 30)
    check('24h_spinup_2h', (windows.loc[windows.window_hours == 24, 'spinup_at_window_start_h'] == 2).all())
    check('window_classification', (windows.loc[windows.context == 'pre_event_complete', 'end_beijing'] == END).all() and (windows.loc[windows.context == 'cross_event', 'end_beijing'] == '2026-08-26T11:00:00+08:00').all())
    check('unknown_water_probability_preserved', water[['local_water_availability', 'trigger_probability', 'SH2O_top_end_m3_m3']].isna().all().all())
    check('all_figures_computed_and_readable', len(points) > 0)
    (OUT / 'verification.json').write_text(json.dumps(dict(status='passed', checks=checks, test_exit_code=proc.returncode,
        frozen_file_count=len(frozen), limits='Computational consistency only; not independent weather or trigger validation'), ensure_ascii=False, indent=2), encoding='utf-8')
    artifacts = [dict(path=relative(p), bytes=p.stat().st_size, sha256=sha(p)) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != 'artifact_manifest.csv']
    csv(pd.DataFrame(artifacts), 'artifact_manifest.csv')
    print(json.dumps(dict(output=relative(OUT), files=len(artifacts)+1, checks=len(checks), status='passed', frozen_files=len(frozen)), ensure_ascii=False))


if __name__ == '__main__':
    build()
