async function refreshBinaryCharge(){
  try{
    const response=await fetch('api/status',{cache:'no-store'});
    const status=await response.json();
    const decision=status.charge_decision||{};
    $('chargeState').textContent=decision.state||'—';
    $('chargeTarget').textContent=(decision.recommended_charge_request||'—').toUpperCase();
    $('chargeVoltage').textContent=withUnit(decision.maximum_grid_voltage,'V');
    $('chargeThermalLimit').textContent=withUnit(decision.projected_sunset_shortfall_kwh,'kWh');
    $('chargeExplanation').textContent=decision.explanation||'—';
    $('chargeBlockers').innerHTML=(decision.blockers||[]).map(value=>`<span class="chip">${esc(value)}</span>`).join('');
    $('chargeSummary').innerHTML=metric('Recommended request',(decision.recommended_charge_request||'—').toUpperCase())+metric('Desired request',(decision.desired_charge_request||'—').toUpperCase())+metric('Reason',decision.explanation)+metric('Determining phase',decision.determining_phase)+metric('Maximum voltage',withUnit(decision.maximum_grid_voltage,'V'))+metric('PV state',decision.pv_state)+metric('Export available',withUnit(decision.available_export_w,'W'))+metric('Energy needed by sunset',withUnit(decision.energy_needed_by_sunset_kwh,'kWh'))+metric('Expected chargeable energy',withUnit(decision.expected_chargeable_before_sunset_kwh,'kWh'))+metric('Projected shortfall',withUnit(decision.projected_sunset_shortfall_kwh,'kWh'))+metric('Pending request',decision.pending_request?`${decision.pending_request.toUpperCase()} (${decision.pending_seconds}s)`:'—');
    $('chargeJson').textContent=JSON.stringify(decision,null,2);
    $('chargeTelemetry').innerHTML=(status.charge_telemetry||[]).slice(-20).reverse().map(item=>`<div class="log"><span>${esc(new Date(item.timestamp).toLocaleString())}</span><span>${esc((item.request||'—').toUpperCase())} · ${esc(item.state)} · ${esc(item.maximum_voltage??'—')} V · ${esc(item.reason)}</span></div>`).join('');
  }catch(error){
    $('chargeExplanation').textContent=error.message;
  }
}
refreshBinaryCharge();setInterval(refreshBinaryCharge,5000);
