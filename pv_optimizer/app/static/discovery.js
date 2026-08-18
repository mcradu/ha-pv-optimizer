async function refreshControlCandidates(){
  try{
    const response=await fetch('api/status',{cache:'no-store'});
    const status=await response.json();
    $('discoveryError').textContent=status.discovery_error||'';
    $('controlCandidates').innerHTML=(status.control_candidates||[]).map(item=>{
      const attributes=item.attributes||{};
      const options=Array.isArray(attributes.options)?attributes.options.join(' · '):'';
      const details=options||[attributes.min,attributes.max,attributes.step,attributes.unit_of_measurement].filter(value=>value!=null).join(' · ');
      return `<div class="entity"><strong>${esc(item.entity_id)}</strong><span class="ok">${esc(item.state)}</span><small>${esc(details||attributes.friendly_name||'')}</small></div>`;
    }).join('')||'<p>No relevant writable entities discovered.</p>';
  }catch(error){
    $('discoveryError').textContent=error.message;
  }
}
refreshControlCandidates();setInterval(refreshControlCandidates,30000);
