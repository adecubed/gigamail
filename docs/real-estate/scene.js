import * as THREE from 'three';
export function startScene({reduced,paused}) {
 const host=document.querySelector('#scene'),canvas=document.querySelector('#network'),story=document.querySelector('#story');
 let renderer;try{renderer=new THREE.WebGLRenderer({canvas,alpha:true,antialias:!matchMedia('(max-width:700px)').matches,powerPreference:'low-power'});}catch{throw new Error("WebGL unavailable");}
 document.body.classList.add("webgl-ready");
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(38,1,.1,100);camera.position.set(0,0,16);
 const group=new THREE.Group();scene.add(group);
 const mobile=()=>matchMedia('(max-width:700px)').matches;
 const positions=[[0,0,0],[-3.7,2.65,.6],[3.3,2.85,-.7],[4.3,.1,.5],[2.8,-2.7,-.5],[-.8,-3.5,.8],[-4.3,-2,0],[-4.5,.5,-.6]].map(p=>new THREE.Vector3(...p));
 const colors=[0xff815b,0xc8b8ff,0xffbf8b,0xc8b8ff,0xc8b8ff,0xffbf8b,0xb4d4c5,0xc0c0cc];
 const nodes=positions.map((p,i)=>{const mesh=new THREE.Mesh(new THREE.IcosahedronGeometry(i? .07:.18,1),new THREE.MeshBasicMaterial({color:colors[i]}));mesh.position.copy(p);group.add(mesh);return mesh;});
 const linePositions=new Float32Array(7*6),lineGeometry=new THREE.BufferGeometry();lineGeometry.setAttribute('position',new THREE.BufferAttribute(linePositions,3));const lineMaterial=new THREE.LineBasicMaterial({color:0xff815b,transparent:true,opacity:.3});group.add(new THREE.LineSegments(lineGeometry,lineMaterial));
 const count=mobile()?44:110,particlePositions=new Float32Array(count*3),seeds=[];
 let seed=731;function random(){seed=(seed*16807)%2147483647;return(seed-1)/2147483646;}
 for(let i=0;i<count;i++)seeds.push({x:(random()-.5)*16,y:(random()-.5)*9,z:(random()-.5)*5,s:random(),target:i%4});
 const particleGeometry=new THREE.BufferGeometry();particleGeometry.setAttribute('position',new THREE.BufferAttribute(particlePositions,3));const particleMaterial=new THREE.PointsMaterial({color:0xffad8c,size:.045,transparent:true,opacity:.7});group.add(new THREE.Points(particleGeometry,particleMaterial));
 const envelopes=[];const envGeometry=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-.13,.08,0),new THREE.Vector3(.13,.08,0),new THREE.Vector3(.13,.08,0),new THREE.Vector3(.13,-.08,0),new THREE.Vector3(.13,-.08,0),new THREE.Vector3(-.13,-.08,0),new THREE.Vector3(-.13,-.08,0),new THREE.Vector3(-.13,.08,0),new THREE.Vector3(-.13,.08,0),new THREE.Vector3(0,-.015,0),new THREE.Vector3(0,-.015,0),new THREE.Vector3(.13,.08,0)]);
 const envMaterial=new THREE.LineBasicMaterial({color:0xdcc0b4,transparent:true,opacity:.65});for(let i=0;i<(mobile()?8:22);i++){const e=new THREE.LineSegments(envGeometry,envMaterial);group.add(e);envelopes.push(e);}
 const ringMaterial=new THREE.LineBasicMaterial({color:0xff815b,transparent:true,opacity:.1});for(const radius of [1.3,2.8,4.5,6.2]){const pts=[];for(let j=0;j<=100;j++){const a=j/100*Math.PI*2;pts.push(new THREE.Vector3(Math.cos(a)*radius,Math.sin(a)*radius, -1.8));}const ring=new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),ringMaterial);ring.rotation.x=.45;group.add(ring);}
 const buttons=[...document.querySelectorAll('[data-node]')],copy=document.querySelector('.hero-copy'),scrollCopy=document.querySelector('.scroll-copy'),categories=document.querySelector('.stage-categories'),meta=document.querySelector('.scene-meta');
 let time=0,last=0,raf=0,visible=true,pointer={x:0,y:0},width=1,height=1,lastStage=-1;const clamp=(n)=>Math.max(0,Math.min(1,n));const smooth=n=>{n=clamp(n);return n*n*(3-2*n);};
 function resize(){width=host.clientWidth;height=host.clientHeight;renderer.setPixelRatio(Math.min(devicePixelRatio,mobile()?1.25:1.75));renderer.setSize(width,height,false);camera.aspect=width/height;camera.position.z=mobile()?18:16;camera.updateProjectionMatrix();}
 const ro=new ResizeObserver(resize);ro.observe(host);
 const project=new THREE.Vector3();
 function draw(ts){raf=0;const delta=Math.min((ts-last)/1000,.04)||0;last=ts;if(!paused()&&!reduced())time+=delta;
 const p=reduced()?0:clamp(-story.getBoundingClientRect().top/(story.offsetHeight-innerHeight));
 const transform=smooth((p-.08)/.22),chaos=smooth((p-.2)/.16),processing=smooth((p-.4)/.22),structure=smooth((p-.67)/.25);
 copy.style.opacity=String(1-transform);copy.style.pointerEvents=transform>.7?'none':'';copy.inert=transform>.7;
 scrollCopy.style.opacity=String(transform);scrollCopy.setAttribute('aria-hidden',transform<.7?'true':'false');categories.style.opacity=String(structure);document.querySelector('#progress').style.width=p*100+'%';
 const stage=p<.4?0:p<.67?1:2;if(stage!==lastStage){lastStage=stage;document.querySelector('#stage-label').textContent=['INBOX CHAOS','GIGAMAIL PROCESSING','STRUCTURED BUSINESS'][stage];document.querySelector('#stage-title').innerHTML=['I messaggi sono sparsi.<br>Il lavoro è connesso.','Il contesto prende forma.','Ogni informazione.<br>Al posto giusto.'][stage];document.querySelector('#stage-description').textContent=['Ogni email contiene un pezzo della stessa storia.','Persone, documenti e conversazioni si incontrano.','Immobili, clienti, documenti e azioni. Pronti per il tuo agente.'][stage];}
 if(mobile()){host.style.top=(470*(1-transform)+innerHeight*.37*transform)+'px';host.style.height=(330*(1-transform)+innerHeight*.4*transform)+'px';}else{host.style.left=(44*(1-transform))+'%';host.style.top=(16+15*transform)+'%';host.style.height=(73-17*transform)+'%';}
 meta.style.opacity=String(1-transform);group.rotation.y=reduced()?0:pointer.x*.065;group.rotation.x=reduced()?0:-pointer.y*.045;
 nodes.forEach((mesh,i)=>{mesh.position.copy(positions[i]);mesh.visible=chaos<.9;mesh.updateMatrixWorld();project.copy(mesh.position);group.localToWorld(project);project.project(camera);buttons[i].style.left=(project.x*.5+.5)*width+'px';buttons[i].style.top=(-project.y*.5+.5)*height+'px';buttons[i].style.opacity=String(1-chaos);buttons[i].style.visibility=chaos>.85?'hidden':'visible';buttons[i].inert=chaos>.85;});
 for(let i=0;i<7;i++){linePositions.set([0,0,0,...nodes[i+1].position.toArray()],i*6);}lineGeometry.attributes.position.needsUpdate=true;lineMaterial.opacity=.3*(1-chaos);
 const spread=(1-processing)+structure;for(let i=0;i<count;i++){const s=seeds[i];let x=s.x,y=s.y,z=s.z;if(p<.3){const dest=positions[(i%7)+1],t=(s.s+time*.065)%1;x=THREE.MathUtils.lerp(s.x*1.3,dest.x,t);y=THREE.MathUtils.lerp(s.y*1.3,dest.y,t);z=THREE.MathUtils.lerp(s.z,dest.z,t);}else{const tx=(s.target-1.5)*3.8+(s.s-.5)*1.8,ty=-.8+Math.sin(s.s*30)*1.6;x=THREE.MathUtils.lerp(s.x*(1-processing),tx,structure);y=THREE.MathUtils.lerp(s.y*(1-processing),ty,structure);z=s.z*spread*.45;}
 particlePositions.set([x,y,z],i*3);if(i<envelopes.length){envelopes[i].position.set(x,y,z);envelopes[i].rotation.z=reduced()?0:Math.sin(time*.35+s.s*10)*.12;}}
 particleGeometry.attributes.position.needsUpdate=true;renderer.render(scene,camera);if(visible&&!document.hidden&&!reduced()&&!paused())raf=requestAnimationFrame(draw);
 }
 function invalidate(){if(!raf)raf=requestAnimationFrame(draw);}function onPointer(e){pointer.x=e.clientX/innerWidth*2-1;pointer.y=e.clientY/innerHeight*2-1;if(!paused())invalidate();}function onVisibility(){if(!document.hidden)invalidate();}
 const io=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible)invalidate();else if(raf){cancelAnimationFrame(raf);raf=0;}},{threshold:0});io.observe(story);
 window.addEventListener('scroll',invalidate,{passive:true});window.addEventListener('resize',invalidate);if(!mobile())window.addEventListener('pointermove',onPointer,{passive:true});document.addEventListener('visibilitychange',onVisibility);window.addEventListener('scene-state',invalidate);resize();invalidate();
 return()=>{cancelAnimationFrame(raf);ro.disconnect();io.disconnect();window.removeEventListener('scroll',invalidate);window.removeEventListener('resize',invalidate);window.removeEventListener('pointermove',onPointer);document.removeEventListener('visibilitychange',onVisibility);window.removeEventListener('scene-state',invalidate);scene.traverse(o=>{o.geometry?.dispose();if(o.material)o.material.dispose();});renderer.dispose();};
}
