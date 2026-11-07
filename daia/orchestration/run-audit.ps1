<#
 DAIA - auditoria orquestrada (V4 / Implementação 08). Pode ser chamada por um agendador externo autorizado.
 O agendamento NÃO concede permissões: mesma credencial somente leitura, mesma política, Jira só como proposta.

 Exemplos:
   powershell -File daia/orchestration/run-audit.ps1 -Environment prod -Source export:C:\daia\evidencias.json -Report
   powershell -File daia/orchestration/run-audit.ps1 -Environment prod -Source export:C:\daia\evidencias.json -Preventive -TriggerId tarefa-diaria
   powershell -File daia/orchestration/run-audit.ps1 -Resume AUD-... -Source export:C:\daia\evidencias.json

 Códigos de saída: 0 CONCLUÍDA · 4 INCOMPLETA · 1 erro/bloqueio de política.
#>
param(
  [string]$Environment,
  [Parameter(Mandatory = $true)][string]$Source,
  [string]$Resume,
  [switch]$Preventive,
  [string]$TriggerId,
  [string]$RequestedBy = $env:USERNAME,
  [switch]$Report
)
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { Write-Host 'Python 3.10+ não encontrado no PATH.'; exit 1 }
if ($Resume) {
  $argsList = @('-m', 'daia.orchestration.cli', 'resume', $Resume, '--source', $Source)
} else {
  if (-not $Environment) { Write-Host 'Informe -Environment (não há ambiente implícito).'; exit 1 }
  $argsList = @('-m', 'daia.orchestration.cli', 'start', '--environment', $Environment, '--source', $Source)
  if ($Preventive) { $argsList += @('--mode', 'preventive', '--trigger-id', $TriggerId, '--requested-by', $RequestedBy) }
  if ($Report) { $argsList += '--report' }
}
Push-Location $repo
try { & $python.Source @argsList; $code = $LASTEXITCODE } finally { Pop-Location }
exit $code
