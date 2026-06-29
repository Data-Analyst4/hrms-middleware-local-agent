# LAN adapter helpers for configure_lan_static_ip.ps1 (dot-source before use).

function Get-DeviceSubnetPrefix {
    param([string]$Ip)
    $parts = $Ip.Trim().Split('.')
    if ($parts.Count -ne 4) { throw "Invalid IP: $Ip" }
    return "$($parts[0]).$($parts[1]).$($parts[2])."
}

function Get-LanAdapterForDevice {
    param([string]$DeviceIp)

    $prefix = Get-DeviceSubnetPrefix -Ip $DeviceIp
    $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {
            $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.IPAddress.StartsWith($prefix)
        })

    if ($addresses.Count -eq 0) {
        throw "No network adapter on the same subnet as the biometric device ($DeviceIp). Connect this PC to the factory LAN, then run again."
    }

    $ranked = foreach ($addr in $addresses) {
        $adapter = Get-NetAdapter -InterfaceIndex $addr.InterfaceIndex -ErrorAction SilentlyContinue
        if (-not $adapter -or $adapter.Status -ne 'Up') { continue }
        $score = 0
        if ($adapter.InterfaceDescription -match 'Ethernet|LAN|Realtek|Intel') { $score += 10 }
        if ($adapter.Name -match 'Wi-Fi|Wireless|WLAN') { $score -= 5 }
        if ($adapter.Virtual -or $adapter.InterfaceDescription -match 'Virtual|Hyper-V|VMware|Loopback|TAP|VPN') { $score -= 20 }
        [PSCustomObject]@{ Address = $addr; Adapter = $adapter; Score = $score }
    }

    $best = @($ranked | Sort-Object Score -Descending | Select-Object -First 1)
    if ($best.Count -eq 0) {
        throw ("No active adapter on subnet " + $prefix)
    }
    return $best[0]
}

function Get-AdapterNetworkSnapshot {
    param([int]$InterfaceIndex)

    $ip = Get-NetIPAddress -InterfaceIndex $InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } |
        Select-Object -First 1
    if (-not $ip) { throw "No IPv4 on interface index $InterfaceIndex" }

    $iface = Get-NetIPInterface -InterfaceIndex $InterfaceIndex -AddressFamily IPv4
    $gateway = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -InterfaceIndex $InterfaceIndex -ErrorAction SilentlyContinue |
        Sort-Object RouteMetric | Select-Object -First 1).NextHop
    if (-not $gateway) {
        $gateway = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
            Sort-Object RouteMetric | Select-Object -First 1).NextHop
    }
    $dns = @(Get-DnsClientServerAddress -InterfaceIndex $InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty ServerAddresses)
    if ($dns.Count -eq 0) { $dns = @('8.8.8.8') }

    $adapter = Get-NetAdapter -InterfaceIndex $InterfaceIndex -ErrorAction SilentlyContinue
    if (-not $adapter) {
        throw "Network adapter (index $InterfaceIndex) not found. Run ipconfig and reconnect Wi-Fi/Ethernet."
    }
    if (-not $gateway -and $ip.IPAddress) {
        $octets = $ip.IPAddress.Trim().Split('.')
        if ($octets.Count -eq 4) {
            $guess = "$($octets[0]).$($octets[1]).$($octets[2]).1"
            Write-Host "WARNING: No default gateway on '$($adapter.Name)'; assuming router $guess" -ForegroundColor Yellow
            Write-Host "  If wrong, set gateway manually in Windows IP settings, then re-run." -ForegroundColor DarkGray
            $gateway = $guess
        }
    }
    $profile = Get-NetConnectionProfile -InterfaceIndex $InterfaceIndex -ErrorAction SilentlyContinue

    return [PSCustomObject]@{
        InterfaceIndex  = $InterfaceIndex
        AdapterName     = $adapter.Name
        MacAddress      = $adapter.MacAddress
        IpAddress       = $ip.IPAddress
        PrefixLength    = $ip.PrefixLength
        Gateway         = $gateway
        DnsServers      = $dns
        DhcpEnabled     = ($iface.Dhcp -eq 'Enabled')
        NetworkCategory = $profile.NetworkCategory
    }
}

function Write-RouterReservationGuide {
    param(
        [string]$OutPath,
        [object]$Snapshot,
        [string]$DeviceIp,
        [string]$SiteCode
    )

    $gateway = $Snapshot.Gateway
    $routerUrl = if ($gateway) { "http://$gateway" } else { "(open your router admin page)" }

    $text = @(
        "HR Middleware - router DHCP reservation (Option A, optional extra safety)"
        "Site: $SiteCode"
        "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        ""
        "This PC already has a Windows static IP (Option B). For belt-and-braces, ask IT to add"
        "a DHCP reservation on the factory router so this PC always gets the same LAN IP."
        ""
        "  PC name:       $env:COMPUTERNAME"
        "  Adapter:       $($Snapshot.AdapterName)"
        "  MAC address:   $($Snapshot.MacAddress)"
        "  Reserved IP:   $($Snapshot.IpAddress)"
        "  Gateway:       $gateway"
        "  Router admin:  $routerUrl"
        ""
        "Biometric device (set static on device menu, DHCP OFF):"
        "  Device IP:     $DeviceIp"
        ""
        "Typical router menu: DHCP Reservation / Address Reservation / Static DHCP"
        "Add row: MAC $($Snapshot.MacAddress) -> IP $($Snapshot.IpAddress)"
        ""
        "Note: ISP public IP changes do NOT affect 192.168.x.x LAN addresses."
    ) -join [Environment]::NewLine

    Set-Content -Path $OutPath -Value $text -Encoding UTF8
    Write-Host ""
    Write-Host "Router DHCP guide saved: $OutPath" -ForegroundColor Cyan
    Write-Host "  MAC $($Snapshot.MacAddress) -> IP $($Snapshot.IpAddress) at $routerUrl" -ForegroundColor Gray
}

function Set-AdapterStaticIp {
    param(
        [object]$Snapshot,
        [string]$NewIp,
        [string]$LogDir
    )

    $idx = $Snapshot.InterfaceIndex
    $prefix = $Snapshot.PrefixLength
    $gateway = $Snapshot.Gateway
    $dns = $Snapshot.DnsServers

    if (-not $gateway) {
        throw "No default gateway on $($Snapshot.AdapterName). Is this PC online on the factory LAN?"
    }

    Write-Host "Setting static IP on '$($Snapshot.AdapterName)'..." -ForegroundColor Cyan
    Write-Host "  IP:      $NewIp / $prefix" -ForegroundColor Gray
    Write-Host "  Gateway: $gateway" -ForegroundColor Gray
    Write-Host "  DNS:     $($dns -join ', ')" -ForegroundColor Gray

    $backup = @{
        saved_at        = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        adapter         = $Snapshot.AdapterName
        interface_index = $idx
        previous_ip     = $Snapshot.IpAddress
        target_ip       = $NewIp
        prefix_length   = $prefix
        gateway         = $gateway
        dns             = $dns
        was_dhcp        = $Snapshot.DhcpEnabled
    }
    $backup | ConvertTo-Json | Set-Content -Path (Join-Path $LogDir "backup.json") -Encoding UTF8

    Set-NetIPInterface -InterfaceIndex $idx -AddressFamily IPv4 -Dhcp Disabled -ErrorAction Stop

    Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -ne $NewIp } |
        Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue

    $existing = Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -eq $NewIp }
    if (-not $existing) {
        if ($gateway) {
            New-NetIPAddress -InterfaceIndex $idx -IPAddress $NewIp -PrefixLength $prefix -DefaultGateway $gateway -ErrorAction Stop | Out-Null
        } else {
            New-NetIPAddress -InterfaceIndex $idx -IPAddress $NewIp -PrefixLength $prefix -ErrorAction Stop | Out-Null
        }
    }

    Set-DnsClientServerAddress -InterfaceIndex $idx -ServerAddresses $dns -ErrorAction SilentlyContinue

    try {
        $profile = Get-NetConnectionProfile -InterfaceIndex $idx -ErrorAction SilentlyContinue
        if ($profile -and $profile.NetworkCategory -eq 'Public') {
            Set-NetConnectionProfile -InterfaceIndex $idx -NetworkCategory Private -ErrorAction SilentlyContinue
            Write-Host "  Network profile set to Private (helps firewall for device live push)." -ForegroundColor Green
        }
    } catch {
        # best effort
    }
}
