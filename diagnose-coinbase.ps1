$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$envPath = Join-Path $PSScriptRoot ".env.coinbase.local"
if (-not (Test-Path $envPath)) { throw ".env.coinbase.local niet gevonden." }

$apiLine = Get-Content $envPath | Where-Object { $_ -like "PUBLIC_API_KEY=*" } | Select-Object -First 1
if (-not $apiLine) { throw "PUBLIC_API_KEY ontbreekt in .env.coinbase.local." }
$apiKey = ($apiLine -split "=", 2)[1].Trim()
if (-not $apiKey) { throw "PUBLIC_API_KEY is leeg." }

$d = Invoke-RestMethod -Uri "http://127.0.0.1:8787/api/coinbase/dashboard/snapshot" -Headers @{ "X-API-Key" = $apiKey }
$a = $d.autonomous
$o = $d.opportunity
$r = $d.readiness
$rr = if ($null -ne $r.PSObject.Properties["readiness"]) { $r.readiness } else { $r }
$b = $d.balances
$probe = if ($null -ne $d.PSObject.Properties["auth_probe"]) { $d.auth_probe } else { $null }
$rt = $d.realtime_orderflow
$diag = $a.entry_diagnostics
$top = @($o.top_candidates)[0]
$lastReject = $diag.last_reject
$arm = $r.arm_persistence
$rules = $a.hard_rules
$assets = @($b.assets)
$usdcRows = @($assets | Where-Object { [string]$_.currency -eq "USDC" } | Select-Object -First 1)
$eurRows = @($assets | Where-Object { [string]$_.currency -eq "EUR" } | Select-Object -First 1)
$agentUsdc = if ($usdcRows.Count -gt 0) { [string]$usdcRows[0].available } elseif ($null -ne $rr.balances) { [string]$rr.balances.USDC } else { "0" }
$agentEur = if ($eurRows.Count -gt 0) { [string]$eurRows[0].available } elseif ($null -ne $rr.balances) { [string]$rr.balances.EUR } else { "0" }
$assetNames = @($assets | ForEach-Object { [string]$_.currency } | Where-Object { $_ }) -join ","
if ([string]::IsNullOrWhiteSpace($assetNames)) { $assetNames = "(geen)" }

[pscustomobject]@{
    status                   = "ok"
    armed                    = [bool]$a.coinbase_armed
    execution_ready          = [bool]$r.execution_ready_now
    persisted_armed          = [bool]$arm.persisted_armed
    auto_resume_eligible     = [bool]$arm.auto_resume_eligible
    failed_gates             = (@($r.execution_failed_gates) -join ",")
    max_daily_loss_pct       = $rules.max_daily_loss_pct
    max_drawdown_pct         = $rules.max_drawdown_pct
    max_single_trade_pct     = $rules.max_single_trade_pct
    cash_reserve_pct         = $rules.min_cash_reserve_pct
    scanned_markets          = $o.scanned_markets
    eligible_scan_markets    = $o.eligible_scan_markets
    balance_source           = $b.balance_source
    balance_authenticated    = [bool]$b.authenticated
    balance_error_category   = $b.error_category
    auth_status              = if ($null -ne $probe) { $probe.status } else { $null }
    auth_authenticated       = if ($null -ne $probe) { [bool]$probe.authenticated } else { $false }
    auth_error_category      = if ($null -ne $probe) { $probe.error_category } else { $null }
    configured_portfolio_id  = $rr.portfolio_id
    assets_seen              = $assetNames
    agent_usdc               = $agentUsdc
    agent_eur                = $agentEur
    fundable_markets         = $o.fundable_markets
    fundable_quotes          = (@($o.fundable_quotes) -join ",")
    evaluated_this_tick      = $o.evaluated_markets_this_tick
    websocket_connected      = [bool]$rt.connected
    websocket_products       = $rt.subscribed_count
    long_signals             = $diag.decisions_seen
    routes_considered        = $diag.routes_considered
    accepted_routes          = $diag.accepted_routes
    best_candidate           = $top.product_id
    best_forecast_bps        = $top.forecast_move_bps
    best_realtime_edge_bps   = $top.realtime_edge_bps
    best_after_cost_product  = $diag.best_after_cost_product
    best_after_cost_edge_bps = $diag.best_after_cost_edge_bps
    last_reject_reason       = $lastReject.reason
    last_reject_product      = $lastReject.product_id
    exploration_attempted    = [bool]$diag.exploration_attempted
    exploration_selected     = [bool]$diag.exploration_selected
    selected_product         = $diag.selected_product
    selected_risk_tier       = $diag.selected_risk_tier
    pending_order            = if ($a.pending_order) { $a.pending_order.product_id + ":" + $a.pending_order.side + ":" + $a.pending_order.order_type } else { "" }
    managed_position         = if ($a.managed_position) { $a.managed_position.product_id } else { "" }
    daily_loss_stop          = [bool]$a.daily_loss_stop
    drawdown_stop            = [bool]$a.drawdown_stop
    current_drawdown_pct     = $a.current_drawdown_pct
    daily_risk_basis_eur     = $a.daily_targets.risk_basis_eur
    daily_loss_limit_eur     = $a.daily_targets.daily_loss_limit_eur
    daily_loss_remaining_eur = $a.daily_targets.daily_loss_remaining_eur
    daily_risk_max_trade_eur = $a.daily_targets.daily_risk_max_trade_eur
    day_trades               = $a.daily_targets.trades_completed
    day_pnl_eur              = $a.daily_targets.profit_eur
} | Format-List
