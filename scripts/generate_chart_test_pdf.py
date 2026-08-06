"""Generate a 3-page PDF with text + charts for MarkItDown download tests."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages

OUT = Path(__file__).resolve().parents[1] / "data" / "samples" / "markitdown_chart_test_3pages.pdf"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    # Type42 嵌入 TrueType，避免默认 Type3 导致抽取变成 /uniXXXX 乱码
    plt.rcParams["pdf.fonttype"] = 42
    plt.rcParams["ps.fonttype"] = 42

    quarters = ["Q1", "Q2", "Q3", "Q4"]
    sales_a = [120, 145, 168, 190]
    sales_b = [98, 112, 130, 155]
    categories = ["华北", "华东", "华南", "西南", "西北"]
    share = [28, 32, 18, 14, 8]
    months = np.arange(1, 13)
    trend = np.array([42, 45, 48, 52, 55, 60, 66, 70, 68, 72, 75, 80])

    with PdfPages(OUT) as pdf:
        # Page 1
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.08, 0.93, "锦盈四季 · 竞品对比分析测试报告", fontsize=18, fontweight="bold")
        fig.text(
            0.08,
            0.89,
            "用途：MarkItDown「下载 MD」看图描述联调样例（含柱状图/饼图/折线图）",
            fontsize=10,
            color="#444444",
        )
        fig.text(0.08, 0.85, "页 1 / 3 · 概述与季度销量对比", fontsize=11)
        fig.text(
            0.08,
            0.78,
            "本测试 PDF 用于验证知识库文档「下载 MD」是否能把图表信息写入 Markdown。\n"
            "请关注：柱状图系列名称、季度刻度、数值高低与竞品差距结论是否被模型描述出来。\n\n"
            "业务背景（虚构）：锦盈四季对标竞品「清禾」在 2025 年的渠道销量。"
            "整体策略为下沉渠道扩张 + 高端系列提价，预期全年份额提升约 3–5 个点。",
            fontsize=10,
            va="top",
        )

        ax = fig.add_axes([0.12, 0.18, 0.76, 0.45])
        x = np.arange(len(quarters))
        w = 0.35
        ax.bar(x - w / 2, sales_a, w, label="锦盈四季", color="#2F6FED")
        ax.bar(x + w / 2, sales_b, w, label="竞品清禾", color="#E67E22")
        ax.set_xticks(x)
        ax.set_xticklabels(quarters)
        ax.set_ylabel("销量（万件）")
        ax.set_title("2025 季度销量对比（柱状图）")
        ax.legend()
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        for i, (a, b) in enumerate(zip(sales_a, sales_b)):
            ax.text(i - w / 2, a + 3, str(a), ha="center", fontsize=8)
            ax.text(i + w / 2, b + 3, str(b), ha="center", fontsize=8)
        fig.text(
            0.08,
            0.08,
            "图 1：锦盈四季全年领先竞品，Q4 差距扩大至 35 万件。",
            fontsize=9,
            color="#333333",
        )
        pdf.savefig(fig)
        plt.close(fig)

        # Page 2
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.08, 0.93, "区域市场份额结构", fontsize=16, fontweight="bold")
        fig.text(0.08, 0.89, "页 2 / 3 · 饼图与区域解读", fontsize=11)
        fig.text(
            0.08,
            0.84,
            "下图展示锦盈四季在五大区域的份额占比。华东、华北合计超过 60%，是主战场；\n"
            "西北份额最低，可作为下一季度渠道试点区域。",
            fontsize=10,
            va="top",
        )
        ax = fig.add_axes([0.18, 0.28, 0.64, 0.48])
        colors = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#B279A2"]
        ax.pie(share, labels=categories, autopct="%1.1f%%", colors=colors, startangle=90)
        ax.set_title("区域份额饼图（%）")
        fig.text(
            0.08,
            0.18,
            "图 2 解读：\n"
            "· 华东 32% / 华北 28%：成熟市场，重点防守\n"
            "· 华南 18%：增长较快，建议加大经销商激励\n"
            "· 西南 14% / 西北 8%：待开拓，配套样板店与导购培训",
            fontsize=10,
            va="top",
        )
        pdf.savefig(fig)
        plt.close(fig)

        # Page 3
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.08, 0.93, "月度线索转化与结论", fontsize=16, fontweight="bold")
        fig.text(0.08, 0.89, "页 3 / 3 · 折线图与行动建议", fontsize=11)
        ax = fig.add_axes([0.12, 0.42, 0.76, 0.40])
        ax.plot(months, trend, marker="o", color="#1B9E77", linewidth=2, label="线索转化率指数")
        ax.fill_between(months, trend, alpha=0.15, color="#1B9E77")
        ax.set_xticks(months)
        ax.set_xlabel("月份")
        ax.set_ylabel("指数")
        ax.set_title("2025 年 1–12 月线索转化率指数（折线图）")
        ax.legend(loc="upper left")
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.annotate(
            "峰值 80",
            xy=(12, 80),
            xytext=(9.5, 76),
            arrowprops=dict(arrowstyle="->", color="#333333"),
            fontsize=9,
        )
        fig.text(
            0.08,
            0.32,
            "综合结论（供看图模型转写校验）：\n"
            "1. 季度销量柱状图显示我方持续领先清禾，Q4 优势最大。\n"
            "2. 区域饼图显示华东+华北主导，西北是增量机会。\n"
            "3. 折线图显示转化率指数从 42 升至 80，全年稳步上行。\n\n"
            "行动建议：巩固华东/华北；华南加码；西北试点；持续跟踪月度转化率。\n"
            "（文件结束）",
            fontsize=10,
            va="top",
        )
        pdf.savefig(fig)
        plt.close(fig)

    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
