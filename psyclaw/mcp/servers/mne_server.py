"""MNE-Python MCP 服务器 — EEG/MEG/ERP 分析(M/EEG 神经科学)。

工具面向心理学 ERP/时频研究。MNE 在则真跑,不在则返回安装提示 +
可直接运行的脚本骨架(确定性,不假装算出结果)。

启动:python -m psyclaw.mcp.servers.mne_server
依赖:pip install mne(可选;未装时工具返回脚本模板)
"""

from __future__ import annotations

import json

from psyclaw.mcp.server_base import MCPServer

srv = MCPServer("psyclaw-mne", "0.1.0")


def _has_mne() -> bool:
    try:
        import mne  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _need_mne(script: str) -> str:
    return ("MNE 未安装(pip install mne)。以下为可复现脚本骨架,"
            "装好后可直接运行:\n\n```python\n" + script + "\n```")


@srv.tool("mne_info", "读取 M/EEG 原始文件信息(通道数、采样率、时长、事件)",
          {"properties": {"path": {"type": "string", "description": "raw 文件(.fif/.edf/.bdf/.set)"}},
           "required": ["path"]})
def mne_info(args: dict) -> str:
    path = args["path"]
    script = (f"import mne\n"
              f"raw = mne.io.read_raw('{path}', preload=False)\n"
              f"print(raw.info)\nprint('时长(s):', raw.times[-1])")
    if not _has_mne():
        return _need_mne(script)
    import mne
    raw = mne.io.read_raw(path, preload=False, verbose="ERROR")
    info = raw.info
    return json.dumps({
        "n_channels": info["nchan"],
        "sfreq": info["sfreq"],
        "ch_types": sorted(set(mne.io.pick.channel_type(info, i)
                               for i in range(info["nchan"]))),
        "duration_sec": float(raw.times[-1]),
        "highpass": info["highpass"], "lowpass": info["lowpass"],
    }, ensure_ascii=False, indent=2)


@srv.tool("mne_preprocess_plan",
          "生成预处理流水线脚本(滤波/重参考/ICA 去伪迹/分段),含 ERP 规范默认值",
          {"properties": {
              "path": {"type": "string"},
              "l_freq": {"type": "number", "description": "高通(Hz),ERP 常用 0.1"},
              "h_freq": {"type": "number", "description": "低通(Hz),ERP 常用 30"},
              "tmin": {"type": "number", "description": "分段起点(s),如 -0.2"},
              "tmax": {"type": "number", "description": "分段终点(s),如 0.8"},
          }, "required": ["path"]})
def mne_preprocess_plan(args: dict) -> str:
    path = args["path"]
    l_freq = args.get("l_freq", 0.1)
    h_freq = args.get("h_freq", 30)
    tmin = args.get("tmin", -0.2)
    tmax = args.get("tmax", 0.8)
    script = f"""import mne
raw = mne.io.read_raw('{path}', preload=True, verbose='ERROR')
raw.set_eeg_reference('average', projection=True)        # 平均参考
raw.filter(l_freq={l_freq}, h_freq={h_freq})             # ERP 带通 {l_freq}-{h_freq} Hz
# ICA 去眼动/心电伪迹
ica = mne.preprocessing.ICA(n_components=0.99, random_state=12345, max_iter='auto')
ica.fit(raw.copy().filter(1.0, None))                    # ICA 拟合用 1Hz 高通更稳
eog_idx, _ = ica.find_bads_eog(raw)
ica.exclude = eog_idx
raw = ica.apply(raw)
# 分段 + 基线校正(ERP 标准:基线取刺激前)
events = mne.find_events(raw)
epochs = mne.Epochs(raw, events, tmin={tmin}, tmax={tmax},
                    baseline=({tmin}, 0), reject=dict(eeg=150e-6),  # 150µV 拒绝阈
                    preload=True)
epochs.save('epochs-epo.fif', overwrite=True)"""
    note = ("\n\n# 严谨性提示:ICA 成分剔除须人工核查(走 HITL 审批);"
            "拒绝阈值与基线窗口须在方法部分报告;随机种子已固定(12345)。")
    head = "MNE 已就绪,以下脚本可直接运行:\n" if _has_mne() \
        else "MNE 未安装(pip install mne)。脚本骨架(装好可直接运行):\n"
    return head + "```python\n" + script + "\n```" + note


@srv.tool("mne_erp_components",
          "ERP 成分测量规范(指定成分→给出标准时间窗/电极/测量方式)",
          {"properties": {"component": {"type": "string",
                          "description": "如 P300/N170/N400/P1/MMN/ERN"}},
           "required": ["component"]})
def mne_erp_components(args: dict) -> str:
    comp = args["component"].upper().replace(" ", "")
    table = {
        "P300": "时窗 300-500ms;电极 Pz/Cz/CPz;测峰值或均幅;oddball 范式",
        "P3": "见 P300",
        "N170": "时窗 130-200ms;电极 P7/P8/PO7/PO8;面孔加工;测峰值",
        "N400": "时窗 300-500ms;电极 Cz/CPz 中央顶区;语义违例;测均幅",
        "P1": "时窗 80-130ms;电极 O1/O2/Oz;早期视觉;测峰值",
        "MMN": "时窗 100-250ms;电极 Fz;偏差-标准差异波;被动听觉",
        "ERN": "时窗 0-100ms(反应后);电极 FCz;错误监控;测峰值",
        "LPP": "时窗 400-1000ms;中央顶区;情绪加工;测均幅",
    }
    hit = table.get(comp)
    if not hit:
        return f"未收录 {comp}。已收录:{', '.join(table)}。请查文献确定时窗/电极后再测量。"
    return (f"[{comp}] {hit}\n严谨性:时窗与电极须**先验**确定(预注册),"
            f"不可看着数据挑窗口(否则是 ERP 版 p-hacking);"
            f"均幅比峰值更抗噪、更推荐;多电极取平均须说明。")


@srv.tool("mne_stats_guidance",
          "M/EEG 统计方法指引(避免多比较陷阱:cluster permutation / TFCE)",
          {"properties": {"question": {"type": "string"}}, "required": []})
def mne_stats_guidance(args: dict) -> str:
    return ("M/EEG 统计核心是**海量多重比较**(通道×时间点×频率)。规范做法:\n"
            "1. 簇水平置换检验(cluster-based permutation,Maris & Oostenveld 2007)"
            "—— MNE: mne.stats.permutation_cluster_1samp_test\n"
            "2. TFCE(threshold-free cluster enhancement)免选簇阈值\n"
            "3. 先验 ROI+时窗可降维成单值,转普通统计(但须预注册)\n"
            "禁止:对每个时间点跑 t 检验不校正;看着地形图挑显著区间事后解释。")


if __name__ == "__main__":
    raise SystemExit(srv.run())
