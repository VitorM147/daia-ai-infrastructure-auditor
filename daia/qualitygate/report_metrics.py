"""Print detector metrics over the labeled SYNTHETIC fixtures. Run: python -m daia.qualitygate.report_metrics"""
from .labeled import metrics, run_all


def main() -> None:
    print("Detectores medidos em casos SINTETICOS rotulados pelos autores (nao e precisao em producao)")
    for name, c in run_all().items():
        m = metrics(c)
        print(f"{name:20} TP={c['tp']:2} FP={c['fp']} FN={c['fn']} TN={c['tn']:2}  precision={m['precision']}  recall={m['recall']}")


if __name__ == "__main__":
    main()
