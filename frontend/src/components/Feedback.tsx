export function Loading({label='Loading'}:{label?:string}) { return <div className="feedback" role="status"><span className="spinner" />{label}…</div> }
export function Empty({title,detail}:{title:string;detail:string}) { return <div className="empty"><div className="empty-icon">✦</div><strong>{title}</strong><span>{detail}</span></div> }
export function ErrorBox({message}:{message:string}) { return <div className="error-box" role="alert">{message}</div> }
