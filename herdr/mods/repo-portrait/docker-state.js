// An inspection error never becomes an empty-stack success.
export function dockerState(data){
 if(!data)return 'loading';
 if(['active','unprepared','stopped','empty'].includes(data.state))return data.state;
 // Compatibility while an older observer is still installed on another machine.
 if(!Array.isArray(data.services))return 'unknown';
 if(data.services.some(s=>['running','restarting','paused'].includes(s.State)))return 'active';
 return data.services.length?'stopped':'empty';
}
export function emptyCopy(state){
 return state==='unprepared'
  ? {title:'No Docker stack here… yet',detail:'This stream hasn’t prepared its containers. Our little whale is waiting for company.'}
  : {title:'No containers running right now',detail:'All quiet in this stream. Our little whale is missing the crew.'};
}
