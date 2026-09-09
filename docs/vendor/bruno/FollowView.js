// Adapted from Bruno Simon, folio-2025 / sources/Game/View.js (MIT).
// Retains spherical camera placement, aspect compensation, tracked focus and zoom smoothing.
// Port: WebGL Three.js, standalone target; omits Game, debug, weather and cinematic dependencies.
import * as THREE from 'three';
export class FollowView {
  constructor(camera) {
    this.camera=camera;
    this.focusPoint={position:new THREE.Vector3(),smoothedPosition:new THREE.Vector3()};
    this.zoom={ratio:.5,smoothedRatio:.5};
    this.spherical={phi:Math.PI*.27,theta:Math.PI*.25,radius:{edges:{min:15,max:30},nonIdealRatioOffset:9},offset:new THREE.Vector3()};
  }
  update(target,delta,overview=false) {
    this.focusPoint.position.copy(target);
    const easing=1-Math.exp(-5*delta);
    this.focusPoint.smoothedPosition.lerp(this.focusPoint.position,easing);
    this.zoom.smoothedRatio=THREE.MathUtils.lerp(this.zoom.smoothedRatio,this.zoom.ratio,Math.min(1,delta*10));
    const overflow=Math.max(1,(1920/1080)/this.camera.aspect)-1;
    const max=this.spherical.radius.edges.max+overflow*this.spherical.radius.nonIdealRatioOffset;
    const radius=overview?max*1.8:THREE.MathUtils.lerp(this.spherical.radius.edges.min,max,1-this.zoom.smoothedRatio);
    this.spherical.offset.setFromSphericalCoords(radius,this.spherical.phi,this.spherical.theta);
    this.camera.position.copy(this.focusPoint.smoothedPosition).add(this.spherical.offset);
    this.camera.lookAt(this.focusPoint.smoothedPosition);
  }
}
