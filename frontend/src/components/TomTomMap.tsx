import { useMemo, useState } from 'react'
import { Minus, Plus } from 'lucide-react'
import './tomtom-map.css'

type Coordinate = [number, number] // [latitude, longitude]
type Props = { origin: Coordinate; destination: Coordinate; route: Coordinate[]; mapKey: string }
const WIDTH = 900
const HEIGHT = 380
const SIZE = 256
const clamp = (x:number, lo:number, hi:number) => Math.min(hi, Math.max(lo, x))
const project = ([lat, lon]:Coordinate, zoom:number) => {
  const scale = SIZE * 2 ** zoom
  const sin = Math.sin(clamp(lat,-85,85) * Math.PI / 180)
  return {x:(lon + 180) / 360 * scale,y:(0.5-Math.log((1+sin)/(1-sin))/(4*Math.PI))*scale}
}

/** TomTom Raster Map Display tiles with a real road-route overlay; no old/retired web SDK. */
export default function TomTomMap({origin,destination,route,mapKey}:Props){
  const [zoomOffset,setZoomOffset]=useState(0)
  const calculated=useMemo(()=>{
    const all=[origin,destination,...route]
    let bestZoom=3
    for(let z=16;z>=3;z--){
      const p=all.map(c=>project(c,z))
      const spreadX=Math.max(...p.map(x=>x.x))-Math.min(...p.map(x=>x.x))
      const spreadY=Math.max(...p.map(x=>x.y))-Math.min(...p.map(x=>x.y))
      if(spreadX<WIDTH*.79 && spreadY<HEIGHT*.69){bestZoom=z;break}
    }
    const zoom=clamp(bestZoom+zoomOffset,3,18)
    const allPixels=all.map(p=>project(p,zoom))
    const xs=allPixels.map(p=>p.x), ys=allPixels.map(p=>p.y)
    const centerX=(Math.min(...xs)+Math.max(...xs))/2
    const centerY=(Math.min(...ys)+Math.max(...ys))/2
    const place=(p:Coordinate)=>{
      const a=project(p,zoom)
      return {x:a.x-centerX+WIDTH/2,y:a.y-centerY+HEIGHT/2}
    }
    const tiles=[] as {id:string;x:number;y:number;url:string}[]
    const firstX=Math.floor((centerX-WIDTH/2)/SIZE),lastX=Math.ceil((centerX+WIDTH/2)/SIZE)
    const firstY=Math.floor((centerY-HEIGHT/2)/SIZE),lastY=Math.ceil((centerY+HEIGHT/2)/SIZE)
    const max=2**zoom
    for(let x=firstX;x<=lastX;x++)for(let y=firstY;y<=lastY;y++){
      if(y<0||y>=max)continue
      const wrapX=((x%max)+max)%max
      const url=`https://api.tomtom.com/map/1/tile/basic/main/${zoom}/${wrapX}/${y}.png?key=${encodeURIComponent(mapKey)}`
      tiles.push({id:`${x}-${y}`,x:x*SIZE-centerX+WIDTH/2,y:y*SIZE-centerY+HEIGHT/2,url})
    }
    const road=route.map(place).map(p=>`${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
    return {tiles,road,user:place(origin),branch:place(destination),hasRoute:route.length>=2}
  },[origin[0],origin[1],destination[0],destination[1],route,mapKey,zoomOffset])
  return <div className="tomtom-map" aria-label="TomTom road map showing customer and destination">
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%" height="100%" role="img" aria-label="Route from your GPS location to your appointment">
      <defs><clipPath id="tomtom-map-viewport"><rect width={WIDTH} height={HEIGHT}/></clipPath></defs>
      <g clipPath="url(#tomtom-map-viewport)">
       <rect width={WIDTH} height={HEIGHT} fill="#ecece8"/>
       {calculated.tiles.map(t=><image key={t.id} href={t.url} x={t.x} y={t.y} width={SIZE+0.5} height={SIZE+0.5}/>) }
       {calculated.hasRoute&&<><polyline points={calculated.road} fill="none" stroke="#fff" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round"/><polyline points={calculated.road} fill="none" stroke="#2356cf" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/></>}
       <circle cx={calculated.user.x} cy={calculated.user.y} r="12" fill="#fff" opacity=".94"/>
       <circle cx={calculated.user.x} cy={calculated.user.y} r="8" fill="#2c66e7" stroke="#fff" strokeWidth="2"/>
       <circle cx={calculated.branch.x} cy={calculated.branch.y} r="15" fill="#fff" opacity=".94"/>
       <circle cx={calculated.branch.x} cy={calculated.branch.y} r="10" fill="#1f9a74" stroke="#fff" strokeWidth="3"/>
      </g>
    </svg>
    <div className="tomtom-map-controls" aria-label="Map zoom controls">
      <button title="Zoom in" aria-label="Zoom in" onClick={()=>setZoomOffset(z=>Math.min(5,z+1))}><Plus size={17}/></button>
      <button title="Zoom out" aria-label="Zoom out" onClick={()=>setZoomOffset(z=>Math.max(-8,z-1))}><Minus size={17}/></button>
    </div>
    <div className="tomtom-map-legend"><span className="tomtom-dot tomtom-dot-user"/> You <span className="tomtom-dot tomtom-dot-branch"/> Appointment</div>
    <span className="tomtom-map-attribution"><a href="https://www.tomtom.com" target="_blank" rel="noreferrer">© TomTom</a></span>
  </div>
}
