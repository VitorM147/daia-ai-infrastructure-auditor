import unittest

from daia.resolution.generator import render_guide
from daia.resolution.models import FindingGuide, InvestigationStep, ResolutionOption
from daia.resolution.validator import validate_guide


class ResolutionGuideTests(unittest.TestCase):
    def guide(self):
        return FindingGuide(
            finding_id="DAIA-SYN-001", title="Synthetic memory trend", priority="P2", status="ATIVO",
            environment="prod", service="synthetic-service", resource="pod/synthetic-1",
            team="team-synthetic", team_validation="tag sintética; não validada", analysis_timestamp="2026-01-05T12:00:00Z",
            analysis_window="2026-01-05T00:00:00Z/2026-01-05T12:00:00Z", fingerprint="synthetic|memory|trend",
            executive_summary="Memory is trending upward; current threshold is not reached.", business_impact="potencial",
            evidence=("OBSERVADO: cinco pontos sintéticos",), metrics_queries=("synthetic.metric{service:synthetic-service}",),
            sanitized_logs=("NÃO VERIFICADO: nenhum log necessário",), traces=("NÃO VERIFICADO",),
            events_changes=("NÃO VERIFICADO",), history=("Baseline sintético de cinco pontos",), alerting=("Monitor sintético não configurado",),
            links=("https://app.datadoghq.com/metric/explorer (não validado)",), symptoms=("Uso crescente",),
            expected_behavior="uso abaixo do limite e estável", abnormal_behavior="inclinação positiva", causes=("carga crescente (HIPÓTESE)",),
            evidence_for=("série ordenada",), evidence_against=("limite ainda não atingido",), alternatives=("sazonalidade",),
            confidence="média-baixa", unverified=("causa operacional",),
            investigation_steps=(InvestigationStep(1, "Confirmar tendência", "Metrics Explorer", "serviço sintético", "query sintética", "cinco pontos", "comparar baseline", "recoletar janela", True),),
            resolution_options=(ResolutionOption("A", "ajustar capacidade se tendência persistir", "evita saturação", ("aprovação",), ("custo",), "gestão de mudança", "comando-sintético", "uso abaixo do limite", "parar se erro aumentar", "reverter alteração"),),
            post_validation=("Observar duas janelas equivalentes; aceite: uso abaixo do limite e sem aumento de erros.",),
            prevention=("Criar monitor de tendência com volume mínimo.",),
        )

    def test_rendered_guide_is_complete(self):
        result = validate_guide(render_guide(self.guide()))
        self.assertTrue(result.valid, result.errors)

    def test_validator_rejects_missing_human_label(self):
        text = render_guide(self.guide()).replace("EXECUÇÃO HUMANA — NÃO EXECUTAR PELO AGENTE", "EXECUTAR")
        result = validate_guide(text)
        self.assertFalse(result.valid)
        self.assertTrue(any("human-execution" in error for error in result.errors))

    def test_validator_rejects_incomplete_causal_claim(self):
        text = render_guide(self.guide()).replace("- **Evidências contra:**\n- limiar ainda não atingido\n", "").replace("- **Hipóteses alternativas:**\n- sazonalidade\n", "") + "\nCausa: confirmada\n"
        result = validate_guide(text)
        self.assertFalse(result.valid)
        self.assertTrue(any("counter-evidence" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
