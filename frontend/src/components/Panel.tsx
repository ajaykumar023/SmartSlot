import type { ReactNode } from 'react'
export default function Panel({title, action, children, className=''}:{title?:string; action?:ReactNode; children:ReactNode; className?:string}) { return <section className={`panel ${className}`}>{(title||action)&&<header className="panel-head">{title&&<h2>{title}</h2>}{action}</header>}{children}</section> }
