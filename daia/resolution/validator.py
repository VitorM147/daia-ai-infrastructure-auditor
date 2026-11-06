"""Completeness and safety validator for generated human guides."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class GuideValidation:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_guide(text: str) -> GuideValidation:
    errors: list[str] = []
    warnings: list[str] = []
    required_sections = ["IDENTIFICAÇÃO", "EVIDÊNCIAS", "DIAGNÓSTICO", "GUIA DE INVESTIGAÇÃO HUMANA", "CORREÇÃO", "VALIDAÇÃO PÓS-CORREÇÃO E ACEITE", "PREVENÇÃO E ACOMPANHAMENTO"]
    for section in required_sections:
        if section not in text:
            errors.append(f"missing section: {section}")
    for field in ["Ambiente", "Serviço", "Recurso", "Timestamp", "Janela", "Fingerprint", "Confiança", "Não verificado", "Jira"]:
        if field not in text:
            errors.append(f"missing field: {field}")
    if "SOMENTE LEITURA" not in text:
        errors.append("diagnostic steps are not explicitly read-only")
    if "EXECUÇÃO HUMANA — NÃO EXECUTAR PELO AGENTE" not in text:
        errors.append("mutation instruction lacks mandatory human-execution label")
    if re.search(r"(?i)causa\s*:\s*confirmada", text) and ("evidências contra" not in text.lower() or "hipóteses alternativas" not in text.lower()):
        errors.append("confirmed cause lacks counter-evidence or alternatives")
    if "http://" in text:
        warnings.append("insecure URL scheme present; validate source before use")
    if "https://" not in text and "caminho" not in text.lower():
        warnings.append("no direct URL or manual navigation path found")
    if re.search(r"(?i)reiniciar|delete|terminate|destroy", text) and "riscos" not in text.lower():
        errors.append("potentially destructive action lacks risk section")
    return GuideValidation(not errors, tuple(errors), tuple(warnings))
