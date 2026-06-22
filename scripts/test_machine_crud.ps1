param(
    [string]$BaseUrl = "http://127.0.0.1:8080",
    [string]$ApiKey = "dev-middleware-key",
    [string]$MachineIp = "192.168.29.44",
    [int]$MachinePort = 5005,
    [int]$MachinePassword = 0,
    [int]$MachineNumber = 1,
    [string]$DeviceId = "DEV-LIVE-01",
    [string]$EmployeeCode = "TEST230",
    [int]$UserId = 230,
    [string]$EmployeeName = "API Test User",
    [string]$CardNo = "9000230",
    [switch]$SkipDelete
)

$ErrorActionPreference = "Stop"
$headers = @{ "x-api-key" = $ApiKey }
$dll = (Resolve-Path "sdk_extracted/20211204-SBXPC-1/bin/SBXPCDLL64.dll").Path

function Invoke-Mw {
    param(
        [string]$Method,
        [string]$Path,
        [object]$Body = $null,
        [hashtable]$ExtraHeaders = @{}
    )
    $uri = "$BaseUrl$Path"
    $params = @{
        Method      = $Method
        Uri         = $uri
        ContentType = "application/json"
        Headers     = ($headers + $ExtraHeaders)
    }
    if ($null -ne $Body) {
        $params.Body = ($Body | ConvertTo-Json -Depth 12 -Compress)
    }
    Write-Host "`n==> $Method $Path" -ForegroundColor Cyan
    $resp = Invoke-RestMethod @params
    $resp | ConvertTo-Json -Depth 8
    return $resp
}

Write-Host "Middleware machine CRUD test" -ForegroundColor Green
Write-Host "Base: $BaseUrl | Machine: $MachineIp`:$MachinePort | Employee: $EmployeeCode (user_id=$UserId)"

# 0) Health
Invoke-Mw -Method GET -Path "/health" -ExtraHeaders @{}

# 1) Register device (ERP would do this once per gate)
Invoke-Mw -Method POST -Path "/api/v1/devices" -Body @{
    device_id          = $DeviceId
    device_name        = "Live Gate"
    site_id            = "SITE-01"
    ip                 = $MachineIp
    port               = $MachinePort
    timezone           = "Asia/Kolkata"
    is_active          = $true
    sdk_protocol       = "sbxpc_tcp"
    machine_password   = [string]$MachinePassword
}

# 2) Test connection
$conn = Invoke-Mw -Method POST -Path "/api/machine/test-connection" -Body @{
    device_id = $DeviceId
}
if (-not $conn.connected) {
    throw "Machine connection failed"
}

# 3) Create in middleware + push to machine
$create = Invoke-Mw -Method POST -Path "/api/v1/employees" -Body @{
    employee_code = $EmployeeCode
    employee_name = $EmployeeName
    card_no       = $CardNo
    department    = "OPERATIONS"
    designation   = "TESTER"
    machine       = @{
        sync_to_machine = $true
        device_id       = $DeviceId
        user_id         = $UserId
        user_name       = $EmployeeName
        card_no         = $CardNo
        enable          = $true
    }
}
if ($create.machine_sync.requested -and -not $create.machine_sync.success) {
    throw "Create + machine sync failed"
}

# 4) Read from machine
Invoke-Mw -Method POST -Path "/api/machine/employees/$EmployeeCode/read" -Body @{
    device_id = $DeviceId
    user_id   = $UserId
    include_user_name = $true
}

# 5) Update middleware + push to machine
Invoke-Mw -Method PATCH -Path "/api/v1/employees/$EmployeeCode" -Body @{
    employee_name = "$EmployeeName Updated"
    phone_no      = "9999999999"
}
Invoke-Mw -Method PUT -Path "/api/machine/employees/$EmployeeCode" -Body @{
    device_id = $DeviceId
    user_id   = $UserId
    user_name = "$EmployeeName Updated"
    card_no   = $CardNo
    enable    = $true
}

# 6) Disable then enable
Invoke-Mw -Method POST -Path "/api/machine/employees/$EmployeeCode/disable" -Body @{
    device_id = $DeviceId
    user_id   = $UserId
    all_slots = $true
}
Invoke-Mw -Method POST -Path "/api/machine/employees/$EmployeeCode/enable" -Body @{
    device_id = $DeviceId
    user_id   = $UserId
    all_slots = $true
}

# 7) Delete from machine (optional)
if (-not $SkipDelete) {
    Invoke-Mw -Method DELETE -Path "/api/machine/employees/$EmployeeCode" -Body @{
        device_id = $DeviceId
        user_id   = $UserId
        all_slots = $true
    }
    Invoke-Mw -Method POST -Path "/api/machine/employees/$EmployeeCode/read" -Body @{
        device_id = $DeviceId
        user_id   = $UserId
    }
}

Write-Host "`nAll steps completed." -ForegroundColor Green
