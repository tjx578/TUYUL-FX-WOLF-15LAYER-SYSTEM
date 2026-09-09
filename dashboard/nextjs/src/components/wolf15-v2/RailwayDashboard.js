'use client';
import {createElement, useEffect, useRef, useState} from 'react';

/** Presentation only. Existing server-side viewer auth and GET helpers stay in the app.
 * existingEvidencePage: the ORIGINAL three-panel React subtree (do not copy its data).
 * snapshot: normalized, server-redacted model from the same existing reads.
 * route/onNavigate: optional existing Next router integration; otherwise hash navigation.
 */
export default function RailwayDashboard({snapshot,existingEvidencePage,onRefresh,onLogout,route,onNavigate,routeBase}) {
  const host=useRef(null);
  const [ready,setReady]=useState(false);
  const [loggedOut,setLoggedOut]=useState(false);
  const [loadFailed,setLoadFailed]=useState(false);
  useEffect(()=>{let mounted=true;import('./dashboard-element.mjs').then(()=>customElements.whenDefined('wolf15-dashboard')).then(()=>{if(mounted)setReady(true);}).catch(()=>{if(mounted)setLoadFailed(true);});return()=>{mounted=false;};},[]);
  useEffect(()=>{if(host.current)host.current.snapshot=loggedOut?{schemaVersion:'wolf15.ui.v2',connection:'session_expired'}:snapshot;},[snapshot,loggedOut]);
  useEffect(()=>{
    const el=host.current;if(!el)return;
    const refresh=()=>onRefresh?.();const logout=()=>{setLoggedOut(true);onLogout?.();};
    const navigate=e=>onNavigate?.(e.detail.route);
    el.addEventListener('wolf15:refresh',refresh);el.addEventListener('wolf15:logout',logout);el.addEventListener('wolf15:navigate',navigate);
    el.setAttribute('can-refresh',String(Boolean(onRefresh)));el.setAttribute('can-logout',String(Boolean(onLogout)));
    if(onNavigate)el.setAttribute('external-router','');else el.removeAttribute('external-router');
    if(routeBase)el.setAttribute('route-base',routeBase);else el.removeAttribute('route-base');
    return ()=>{el.removeEventListener('wolf15:refresh',refresh);el.removeEventListener('wolf15:logout',logout);el.removeEventListener('wolf15:navigate',navigate);};
  },[onRefresh,onLogout,onNavigate,routeBase]);
  useEffect(()=>{if(route)host.current?.setAttribute('route',route);},[route]);
  const authorized=ready&&!loggedOut&&snapshot?.connection==='connected';
  return createElement('wolf15-dashboard',{ref:host},loadFailed?createElement('p',{role:'alert'},'Komponen dashboard belum dapat dimuat.'):authorized&&existingEvidencePage?createElement('div',{slot:'system-evidence'},existingEvidencePage):null);
}
