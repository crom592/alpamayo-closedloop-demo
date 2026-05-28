"""One-page PDF report for a single rollout — KADaP PoC deliverable.

Per-rollout artifact:
    - header (scenario, driver, uuid, timestamp)
    - aggregated metrics table (Safety / Comfort / Progress placeholders)
    - embedded matplotlib timeseries (speed / lateral_accel / jerk)

PDFs are written to ``/tmp/kadap-poc-reports/`` (Gradio's allowed_paths
list includes /tmp by default, so gr.File can serve them).
"""

from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import metrics  # noqa: E402
from runner import RolloutRef  # noqa: E402

REPORTS_DIR = Path("/tmp/kadap-poc-reports")


def _metrics_image(m: metrics.RolloutMetrics) -> bytes:
    fig, axes = plt.subplots(3, 1, figsize=(6.5, 4.5), sharex=True)
    axes[0].plot(m.series.t, m.series.speed, color="tab:blue")
    axes[0].set_ylabel("speed (m/s)")
    axes[0].grid(alpha=0.3)
    axes[1].plot(m.series.t, m.series.lateral_accel, color="tab:orange")
    axes[1].set_ylabel("|lat accel| (m/s²)")
    axes[1].grid(alpha=0.3)
    axes[2].plot(m.series.t, m.series.jerk, color="tab:red")
    axes[2].set_ylabel("jerk (m/s³)")
    axes[2].set_xlabel("sim time (s)")
    axes[2].grid(alpha=0.3)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130)
    plt.close(fig)
    return buf.getvalue()


def build_report(rollout: RolloutRef) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    m = metrics.compute(rollout.asl)

    abl = rollout.ablation.replace(" ", "_").replace("/", "_")
    out = REPORTS_DIR / f"report_{rollout.driver}_{abl}_{rollout.rollout_uuid[:8]}.pdf"
    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    story: list = []

    story.append(Paragraph("KADaP Alpamayo Closed-loop 시뮬 리포트", styles["Title"]))
    story.append(
        Paragraph(
            f"생성: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 6 * mm))

    meta_rows = [
        ["scenario", rollout.scenario_id],
        ["driver", rollout.driver],
        ["ablation", rollout.ablation],
        ["rollout uuid", rollout.rollout_uuid],
        ["rollout.asl 크기", f"{rollout.asl.stat().st_size / 1024 / 1024:.2f} MB"],
    ]
    meta_tbl = Table(meta_rows, colWidths=[40 * mm, 130 * mm])
    meta_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(meta_tbl)
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph("집계 메트릭", styles["Heading2"]))
    if m.is_empty:
        story.append(
            Paragraph("⚠ controller_return 메시지 없음 — 시뮬이 1 step 이상 안 돌았음.", styles["Normal"])
        )
    else:
        agg_rows = [
            ["항목", "값"],
            ["n_steps (controller)", f"{m.n_steps}"],
            ["시뮬 시간", f"{m.duration_s:.2f} s"],
            ["평균 속도", f"{m.avg_speed:.2f} m/s"],
            ["최대 속도", f"{m.max_speed:.2f} m/s"],
            ["최대 횡가속도", f"{m.max_lateral_accel:.3f} m/s²"],
            ["최대 jerk", f"{m.max_jerk:.3f} m/s³"],
        ]
        agg_tbl = Table(agg_rows, colWidths=[60 * mm, 50 * mm])
        agg_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#003366")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(agg_tbl)
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("시계열", styles["Heading2"]))
        img = Image(io.BytesIO(_metrics_image(m)))
        img._restrictSize(160 * mm, 110 * mm)
        story.append(img)

    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "<i>본 리포트는 PoC v0 자동 생성입니다. Safety 이벤트(충돌·차선이탈), "
            "Progress(경로 진행률), Plan deviation 분석은 후속 버전에서 추가됩니다.</i>",
            styles["Italic"],
        )
    )

    doc.build(story)
    return out
