<#
 DAIA - suíte de evals COMPORTAMENTAIS (executa o agente sobre o Golden Dataset sintético).
 Complementa run-evals.ps1 (estático); não o substitui.

 Exemplos:
   powershell -File daia/evals/run-behavioral.ps1                         # agente de referência
   powershell -File daia/evals/run-behavioral.ps1 -Agent anthropic -Repeat 3 -Record
   powershell -File daia/evals/run-behavioral.ps1 -Agent command -AgentCmd "python meu_agente.py" -AgentName daia-kiro -AgentVersion 1.0

 Códigos de saída: 0 PASS · 1 BLOQUEADO · 2 PASS com revisão humana pendente · 3 NÃO EXECUTADO/INCOMPLETO.
#>
param(
  [ValidateSet('reference', 'naive', 'anthropic', 'command')][string]$Agent = 'reference',
  [string]$AgentCmd,
  [string]$AgentName,
  [string]$AgentVersion,
  [string]$AgentModel,
  [int]$Repeat = 1,
  [string]$Scenarios,
  [string]$Baseline,
  [switch]$Record,
  [switch]$VerboseReport
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { Write-Error 'Python 3.10+ não encontrado no PATH.'; exit 3 }
$argsList = @('-m', 'daia.evals.framework.runner', 'run', '--agent', $Agent, '--repeat', $Repeat)
if ($AgentCmd) { $argsList += @('--agent-cmd', $AgentCmd) }
if ($AgentName) { $argsList += @('--agent-name', $AgentName) }
if ($AgentVersion) { $argsList += @('--agent-version', $AgentVersion) }
if ($AgentModel) { $argsList += @('--agent-model', $AgentModel) }
if ($Scenarios) { $argsList += @('--scenarios', $Scenarios) }
if ($Baseline) { $argsList += @('--baseline', $Baseline) }
if ($Record) { $argsList += '--record' }
if ($VerboseReport) { $argsList += '--verbose' }
Push-Location $repo
try {
  & $python.Source @argsList
  $code = $LASTEXITCODE
} finally { Pop-Location }
exit $code
