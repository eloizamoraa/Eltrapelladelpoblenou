# Registra una tarea programada de Windows que procesa el buzón cada N minutos.
# Uso (desde la carpeta del proyecto):  .\scripts\registrar_tarea.ps1 [-Minutos 10]
# Para quitarla:  Unregister-ScheduledTask -TaskName "Trapella Facturas" -Confirm:$false
param([int]$Minutos = 10)

$proyecto = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $proyecto ".venv\Scripts\trapella-facturas.exe"
if (-not (Test-Path $exe)) { throw "No existe $exe. Instala antes el proyecto (ver README)." }

$accion = New-ScheduledTaskAction -Execute $exe -Argument "run" -WorkingDirectory $proyecto
$disparador = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $Minutos)
# Si una pasada se alarga, la siguiente no arranca encima.
$ajustes = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName "Trapella Facturas" -Action $accion -Trigger $disparador `
    -Settings $ajustes -Description "Procesa las facturas recibidas por email" -Force | Out-Null
Write-Host "Tarea registrada: cada $Minutos minutos. Registro en $proyecto\logs\"
