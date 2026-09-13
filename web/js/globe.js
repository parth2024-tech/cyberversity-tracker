// ══════════════════════════════════════════════════════════════════════════
// FEATURE 1 & 2: 3D HOLOGRAPHIC RADAR GLOBE (Three.js WebGL)
// Interactive 3D spatial radar mapping 36 sovereign intelligence & AI hubs
// ══════════════════════════════════════════════════════════════════════════

let globeScene, globeCamera, globeRenderer, globeSphere, globeRing, globePoints;
let isGlobeVisible = true;
let isDraggingGlobe = false;
let prevMouseX = 0, prevMouseY = 0;
let globeVelX = 0.002, globeVelY = 0;
let dragStartX = 0, dragStartY = 0;
let hoveredStation = null;
let isNavigatingToStation = false;
let targetRotX = 0, targetRotY = 0;
let globeAnimFrameId = null;
let resumeGlobeAnimation = null;
let pauseGlobeAnimation = null;

function initThreeGlobe() {
  try {
    const container = document.getElementById('three-globe-viewport');
    const tooltip = document.getElementById('globe-tooltip');
    if (!container || typeof THREE === 'undefined') return;

    const w = container.clientWidth || 800;
    const h = container.clientHeight || 300;

    globeScene = new THREE.Scene();
    globeCamera = new THREE.PerspectiveCamera(45, w / h, 0.1, 1000);
    globeCamera.position.z = 4.5;

    // Use low-power GPU profile and balanced pixel ratio to protect laptop battery and thermals
    globeRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
    globeRenderer.setSize(w, h);
    globeRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    container.appendChild(globeRenderer.domElement);

    // Core Obsidian Sphere
    const coreGeo = new THREE.SphereGeometry(1.4, 32, 32);
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0x070a12,
      transparent: true,
      opacity: 0.95
    });
    globeScene.add(new THREE.Mesh(coreGeo, coreMat));

    // Atmospheric Outer Aura Glow (Inverted Normals Shader with Additive Fresnel Falloff)
    const atmoGeo = new THREE.SphereGeometry(1.78, 32, 32);
    const atmoMat = new THREE.ShaderMaterial({
      vertexShader: `
        varying vec3 vNormal;
        void main() {
          vNormal = normalize(normalMatrix * normal);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        varying vec3 vNormal;
        void main() {
          float intensity = pow(0.62 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 2.2);
          gl_FragColor = vec4(0.22, 0.74, 0.98, 1.0) * intensity * 0.85;
        }
      `,
      side: THREE.BackSide,
      blending: THREE.AdditiveBlending,
      transparent: true,
      depthWrite: false
    });
    const atmoMesh = new THREE.Mesh(atmoGeo, atmoMat);
    atmoMesh.renderOrder = 0;
    globeScene.add(atmoMesh);

    // Ambient Cosmic Stardust Particle Cloud
    const starGeo = new THREE.BufferGeometry();
    const starPos = new Float32Array(350 * 3);
    for (let i = 0; i < 350; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos((Math.random() * 2) - 1);
      const dist = 3.2 + Math.random() * 4.5;
      starPos[i * 3]     = dist * Math.sin(phi) * Math.cos(theta);
      starPos[i * 3 + 1] = dist * Math.sin(phi) * Math.sin(theta);
      starPos[i * 3 + 2] = dist * Math.cos(phi);
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
    const starMat = new THREE.PointsMaterial({ size: 0.035, color: 0x94a3b8, transparent: true, opacity: 0.55 });
    const starField = new THREE.Points(starGeo, starMat);
    globeScene.add(starField);

    // Planetary Carrier Sphere (Houses all rotating geography, arcs, and beacons)
    const sphereGeo = new THREE.IcosahedronGeometry(1.6, 3);
    const sphereMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      wireframe: true,
      transparent: true,
      opacity: 0.14
    });
    globeSphere = new THREE.Mesh(sphereGeo, sphereMat);
    globeScene.add(globeSphere);

    // Longitude / Latitude Accent Rings (Titanium Silver)
    for (let i = -2; i <= 2; i++) {
      const ringRad = Math.cos((i * Math.PI) / 6) * 1.62;
      const ringGeo = new THREE.RingGeometry(ringRad - 0.008, ringRad + 0.008, 48);
      const ringMat = new THREE.MeshBasicMaterial({ color: 0x334155, side: THREE.DoubleSide, transparent: true, opacity: 0.25 });
      const ringMesh = new THREE.Mesh(ringGeo, ringMat);
      ringMesh.rotation.x = Math.PI / 2;
      ringMesh.position.y = Math.sin((i * Math.PI) / 6) * 1.62;
      globeSphere.add(ringMesh);
    }

    // Orbital Scanning Sweep Ring (Ethereal Sky Azure)
    const scanRingGeo = new THREE.RingGeometry(1.85, 1.93, 64);
    const scanRingMat = new THREE.MeshBasicMaterial({
      color: 0x60a5fa,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.22
    });
    globeRing = new THREE.Mesh(scanRingGeo, scanRingMat);
    globeRing.rotation.x = Math.PI / 2.8;
    globeScene.add(globeRing);

    // 36 Sovereign Intelligence & AI Research Stations
    const WORLD_STATIONS = [
      { name: 'Beijing AI & CNCERT Command', country: 'CN', flag: '🇨🇳', lat: 39.9042, lon: 116.4074, color: 0xef4444 },
      { name: 'Shanghai AI Lab & Fudan Hub', country: 'CN', flag: '🇨🇳', lat: 31.2304, lon: 121.4737, color: 0xf97316 },
      { name: 'Hangzhou Alibaba Qwen Grid', country: 'CN', flag: '🇨🇳', lat: 30.2741, lon: 120.1551, color: 0xfbbf24 },
      { name: 'Shenzhen Tencent & MindSpore Lab', country: 'CN', flag: '🇨🇳', lat: 22.5431, lon: 114.0579, color: 0x38bdf8 },
      { name: 'Hong Kong GovCERT Radar', country: 'HK', flag: '🇭🇰', lat: 22.3193, lon: 114.1694, color: 0xef4444 },
      { name: 'Tokyo Cyber Command', country: 'JP', flag: '🇯🇵', lat: 35.6762, lon: 139.6503, color: 0x38bdf8 },
      { name: 'London NCSC Node', country: 'GB', flag: '🇬🇧', lat: 51.5074, lon: -0.1278, color: 0x818cf8 },
      { name: 'Paris ANSSI / Mistral', country: 'FR', flag: '🇫🇷', lat: 48.8566, lon: 2.3522, color: 0x34d399 },
      { name: 'Berlin BSI Station', country: 'DE', flag: '🇩🇪', lat: 52.5200, lon: 13.4050, color: 0xfbbf24 },
      { name: 'Brussels CERT-EU / AI Office', country: 'EU', flag: '🇪🇺', lat: 50.8503, lon: 4.3517, color: 0x38bdf8 },
      { name: 'Washington DC CISA / NIST', country: 'US', flag: '🇺🇸', lat: 38.9072, lon: -77.0369, color: 0xfb7185 },
      { name: 'Canberra ACSC Defense', country: 'AU', flag: '🇦🇺', lat: -35.2809, lon: 149.1300, color: 0x34d399 },
      { name: 'Ottawa CCCS Gateway', country: 'CA', flag: '🇨🇦', lat: 45.4215, lon: -75.6972, color: 0x818cf8 },
      { name: 'Singapore SingCERT', country: 'SG', flag: '🇸🇬', lat: 1.3521, lon: 103.8198, color: 0x38bdf8 },
      { name: 'Zurich ETH AI Safety Lab', country: 'CH', flag: '🇨🇭', lat: 47.3769, lon: 8.5417, color: 0xfbbf24 },
      { name: 'Sydney Pacific Radar', country: 'AU', flag: '🇦🇺', lat: -33.8688, lon: 151.2093, color: 0x34d399 },
      { name: 'Bengaluru AI Cyber Hub', country: 'IN', flag: '🇮🇳', lat: 12.9716, lon: 77.5946, color: 0x38bdf8 },
      { name: 'Tel Aviv Threat Intel', country: 'IL', flag: '🇮🇱', lat: 32.0853, lon: 34.7818, color: 0xfb7185 },
      { name: 'Seoul East Asia Defense', country: 'KR', flag: '🇰🇷', lat: 37.5665, lon: 126.9780, color: 0x38bdf8 },
      { name: 'San Francisco Frontier AI Grid', country: 'US', flag: '🇺🇸', lat: 37.7749, lon: -122.4194, color: 0x818cf8 },
      { name: 'New York Financial Telemetry', country: 'US', flag: '🇺🇸', lat: 40.7128, lon: -74.0060, color: 0xfb7185 },
      { name: 'Toronto Vector AI Hub', country: 'CA', flag: '🇨🇦', lat: 43.6532, lon: -79.3832, color: 0x818cf8 },
      { name: 'Amsterdam AMS-IX Cyber Node', country: 'NL', flag: '🇳🇱', lat: 52.3676, lon: 4.9041, color: 0x34d399 },
      { name: 'Stockholm Nordic Defense', country: 'SE', flag: '🇸🇪', lat: 59.3293, lon: 18.0686, color: 0x38bdf8 },
      { name: 'Helsinki Hybrid CoE', country: 'FI', flag: '🇫🇮', lat: 60.1699, lon: 24.9384, color: 0x38bdf8 },
      { name: 'São Paulo Latin America Node', country: 'BR', flag: '🇧🇷', lat: -23.5505, lon: -46.6333, color: 0xfbbf24 },
      { name: 'Cape Town Africa Defense', country: 'ZA', flag: '🇿🇦', lat: -33.9249, lon: 18.4241, color: 0x34d399 },
      { name: 'Oxford AI Governance', country: 'GB', flag: '🇬🇧', lat: 51.7520, lon: -1.2577, color: 0x818cf8 },
      { name: 'Cambridge AI Safety Center', country: 'GB', flag: '🇬🇧', lat: 52.2053, lon: 0.1218, color: 0x38bdf8 },
      { name: 'Taipei TSMC Semiconductor Foundry', country: 'TW', flag: '🇹🇼', lat: 25.0330, lon: 121.5654, color: 0x38bdf8 },
      { name: 'Abu Dhabi TII Falcon & MBZUAI Lab', country: 'AE', flag: '🇦🇪', lat: 24.4539, lon: 54.3773, color: 0xfbbf24 },
      { name: 'New Delhi CERT-In / Cyber Command', country: 'IN', flag: '🇮🇳', lat: 28.6139, lon: 77.2090, color: 0x38bdf8 },
      { name: 'Montreal Mila AI Research Institute', country: 'CA', flag: '🇨🇦', lat: 45.5017, lon: -73.5673, color: 0x818cf8 },
      { name: 'Munich Industrial AI & DFKI Hub', country: 'DE', flag: '🇩🇪', lat: 48.1351, lon: 11.5820, color: 0xfbbf24 },
      { name: 'Veldhoven ASML Semiconductor Foundry', country: 'NL', flag: '🇳🇱', lat: 51.4190, lon: 5.4050, color: 0x34d399 },
      { name: 'Geneva CERN Computing & AI Grid', country: 'CH', flag: '🇨🇭', lat: 46.2044, lon: 6.1432, color: 0x818cf8 }
    ];

    function geoToVector3(lat, lon, radius) {
      const phi = (90 - lat) * (Math.PI / 180);
      const theta = (lon + 180) * (Math.PI / 180);
      const x = -(radius * Math.sin(phi) * Math.cos(theta));
      const z = (radius * Math.sin(phi) * Math.sin(theta));
      const y = (radius * Math.cos(phi));
      return new THREE.Vector3(x, y, z);
    }

    const pointCount = WORLD_STATIONS.length;
    const pointPositions = new Float32Array(pointCount * 3);
    const pointColors = new Float32Array(pointCount * 3);
    const stationHitMeshes = [];
    const stationMeshHitGeo = new THREE.SphereGeometry(0.12, 8, 8);
    const stationMeshHitMat = new THREE.MeshBasicMaterial({ visible: false });

    for (let i = 0; i < pointCount; i++) {
      const st = WORLD_STATIONS[i];
      const v = geoToVector3(st.lat, st.lon, 1.62);
      pointPositions[i * 3]     = v.x;
      pointPositions[i * 3 + 1] = v.y;
      pointPositions[i * 3 + 2] = v.z;

      const c = new THREE.Color(st.color);
      pointColors[i * 3]     = c.r;
      pointColors[i * 3 + 1] = c.g;
      pointColors[i * 3 + 2] = c.b;

      // Hit Target for Interactive Raycasting
      const hitMesh = new THREE.Mesh(stationMeshHitGeo, stationMeshHitMat);
      hitMesh.position.copy(v);
      hitMesh.userData = st;
      globeSphere.add(hitMesh);
      stationHitMeshes.push(hitMesh);
    }

    const pointsGeo = new THREE.BufferGeometry();
    pointsGeo.setAttribute('position', new THREE.BufferAttribute(pointPositions, 3));
    pointsGeo.setAttribute('color', new THREE.BufferAttribute(pointColors, 3));
    const pointsMat = new THREE.PointsMaterial({
      size: 0.085,
      vertexColors: true,
      transparent: true,
      opacity: 0.95
    });
    globePoints = new THREE.Points(pointsGeo, pointsMat);
    globeSphere.add(globePoints);

    // 10 Global AI Great-Circle Synchronization Arcs & Moving Pulses
    const ARC_PAIRS = [
      ['San Francisco Frontier AI Grid', 'Tokyo Cyber Command'],
      ['San Francisco Frontier AI Grid', 'London NCSC Node'],
      ['Bengaluru AI Cyber Hub', 'Singapore SingCERT'],
      ['Beijing AI & CNCERT Command', 'Seoul East Asia Defense'],
      ['Paris ANSSI / Mistral', 'Berlin BSI Station'],
      ['Abu Dhabi TII Falcon & MBZUAI Lab', 'Zurich ETH AI Safety Lab'],
      ['Taipei TSMC Semiconductor Foundry', 'San Francisco Frontier AI Grid'],
      ['New York Financial Telemetry', 'London NCSC Node'],
      ['Sydney Pacific Radar', 'Singapore SingCERT'],
      ['Montreal Mila AI Research Institute', 'Paris ANSSI / Mistral']
    ];

    const stationLookup = {};
    WORLD_STATIONS.forEach(s => { stationLookup[s.name] = s; });

    const aiCurves = [];
    const arcCount = ARC_PAIRS.length;
    const arcPulsePositions = new Float32Array(arcCount * 3);
    const arcProgress = [0.0, 0.12, 0.25, 0.38, 0.5, 0.62, 0.75, 0.88, 0.3, 0.7];
    const arcSpeeds = [0.007, 0.009, 0.006, 0.008, 0.005, 0.007, 0.009, 0.006, 0.008, 0.005];

    const arcLineMat = new THREE.LineBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.38
    });

    ARC_PAIRS.forEach(([nameA, nameB], idx) => {
      const stA = stationLookup[nameA];
      const stB = stationLookup[nameB];
      if (!stA || !stB) return;

      const pA = geoToVector3(stA.lat, stA.lon, 1.62);
      const pB = geoToVector3(stB.lat, stB.lon, 1.62);

      const mid = new THREE.Vector3().addVectors(pA, pB).multiplyScalar(0.5);
      const dist = pA.distanceTo(pB);
      mid.normalize().multiplyScalar(1.62 + dist * 0.22);

      const curve = new THREE.QuadraticBezierCurve3(pA, mid, pB);
      aiCurves.push(curve);

      const curveGeo = new THREE.BufferGeometry().setFromPoints(curve.getPoints(36));
      const curveLine = new THREE.Line(curveGeo, arcLineMat);
      globeSphere.add(curveLine);

      // Initial pulse pos
      const initPoint = curve.getPoint(arcProgress[idx]);
      arcPulsePositions[idx * 3]     = initPoint.x;
      arcPulsePositions[idx * 3 + 1] = initPoint.y;
      arcPulsePositions[idx * 3 + 2] = initPoint.z;
    });

    // Travelling Pulse Particles on Arcs
    const pulseGeo = new THREE.BufferGeometry();
    pulseGeo.setAttribute('position', new THREE.BufferAttribute(arcPulsePositions, 3));
    const pulseMat = new THREE.PointsMaterial({
      size: 0.12,
      color: 0x7dd3fc,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending
    });
    const pulsePoints = new THREE.Points(pulseGeo, pulseMat);
    globeSphere.add(pulsePoints);

    // Reusable objects for zero allocations in rAF loop
    const _tempVec = new THREE.Vector3();
    const _raycaster = new THREE.Raycaster();
    const _mouseNDC = new THREE.Vector2(-999, -999);

    // Raycasting & Mouse move
    container.addEventListener('mousemove', (e) => {
      const rect = container.getBoundingClientRect();
      _mouseNDC.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      _mouseNDC.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      if (isDraggingGlobe) {
        const deltaX = e.clientX - prevMouseX;
        const deltaY = e.clientY - prevMouseY;
        globeVelX = deltaX * 0.005;
        globeVelY = deltaY * 0.005;
        prevMouseX = e.clientX;
        prevMouseY = e.clientY;
        if (tooltip) tooltip.classList.remove('visible');
        return;
      }

      // Test station hover
      _raycaster.setFromCamera(_mouseNDC, globeCamera);
      const intersects = _raycaster.intersectObjects(stationHitMeshes);

      if (intersects.length > 0) {
        hoveredStation = intersects[0].object.userData;
        container.style.cursor = 'pointer';
        if (tooltip) {
          tooltip.innerHTML = `
            <div class="flex items-center gap-1.5">
              <span class="text-sm">${hoveredStation.flag}</span>
              <span class="font-bold text-sky-300">${hoveredStation.name}</span>
            </div>
            <div class="text-[10px] text-slate-400 mt-0.5">Click station to filter feed by ${hoveredStation.country}</div>
          `;
          tooltip.style.left = (e.clientX - rect.left) + 'px';
          tooltip.style.top = (e.clientY - rect.top) + 'px';
          tooltip.classList.add('visible');
        }
      } else {
        hoveredStation = null;
        container.style.cursor = 'grab';
        if (tooltip) tooltip.classList.remove('visible');
      }
    });

    // Mouse drag controls & Click-to-filter
    container.addEventListener('mousedown', (e) => {
      isDraggingGlobe = true;
      isNavigatingToStation = false;
      prevMouseX = e.clientX;
      prevMouseY = e.clientY;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      container.style.cursor = 'grabbing';
    });

    window.addEventListener('mouseup', (e) => {
      if (!isDraggingGlobe) return;
      isDraggingGlobe = false;
      container.style.cursor = hoveredStation ? 'pointer' : 'grab';

      // Detect click without drag (< 6px movement)
      const distDragged = Math.hypot(e.clientX - dragStartX, e.clientY - dragStartY);
      if (distDragged < 6 && hoveredStation) {
        filterByStation(hoveredStation);
      }
    });

    // Window resize handling
    window.addEventListener('resize', () => {
      if (!container || !globeRenderer) return;
      const nw = container.clientWidth;
      const nh = container.clientHeight;
      globeCamera.aspect = nw / nh;
      globeCamera.updateProjectionMatrix();
      globeRenderer.setSize(nw, nh);
    });

    // Smooth Station Navigation & Feed Filtering
    function filterByStation(st) {
      if (!st) return;
      const c = st.country;
      if (typeof setRegionFilter === 'function') {
        if (c === 'CN' || c === 'HK') setRegionFilter('china');
        else if (c === 'IN') setRegionFilter('south_asia');
        else if (c === 'US' || c === 'CA') setRegionFilter('north_america');
        else if (['FR', 'DE', 'GB', 'EU', 'NL', 'CH', 'SE', 'FI'].includes(c)) setRegionFilter('europe');
        else if (['JP', 'KR', 'TW', 'SG', 'AU'].includes(c)) setRegionFilter('apac');
        else if (['IL', 'AE'].includes(c)) setRegionFilter('middle_east');
        else setRegionFilter('all');
      }

      // Target rotation to smoothly face camera
      targetRotY = - (st.lon + 180) * (Math.PI / 180) + Math.PI / 2;
      targetRotX = (st.lat * (Math.PI / 180)) * 0.4;
      isNavigatingToStation = true;
      if (typeof showToast === 'function') showToast(`Station Activated: ${st.flag} ${st.name}`, 'info');
    }

    pauseGlobeAnimation = function() {
      if (globeAnimFrameId) {
        cancelAnimationFrame(globeAnimFrameId);
        globeAnimFrameId = null;
      }
    };

    resumeGlobeAnimation = function() {
      if (isGlobeVisible && !document.hidden && !globeAnimFrameId && globeRenderer && globeScene && globeCamera) {
        globeAnimFrameId = requestAnimationFrame(animateGlobe);
      }
    };

    // Animation Loop (Zero allocations inside frame, completely dormant when hidden)
    function animateGlobe() {
      if (!isGlobeVisible || document.hidden) {
        globeAnimFrameId = null;
        return;
      }

      // Subtle starfield ambient drift
      starField.rotation.y += 0.0003;

      // Planetary rotation & inertia
      if (globeSphere) {
        if (isNavigatingToStation) {
          globeSphere.rotation.y += (targetRotY - globeSphere.rotation.y) * 0.08;
          globeSphere.rotation.x += (targetRotX - globeSphere.rotation.x) * 0.08;
          if (Math.abs(targetRotY - globeSphere.rotation.y) < 0.005) {
            isNavigatingToStation = false;
          }
        } else if (!isDraggingGlobe) {
          globeVelX *= 0.95;
          globeVelY *= 0.95;
          globeSphere.rotation.y += 0.0025 + globeVelX;
          globeSphere.rotation.x += globeVelY;
        } else {
          globeSphere.rotation.y += globeVelX;
          globeSphere.rotation.x += globeVelY;
        }
      }

      if (globeRing) {
        globeRing.rotation.z += 0.008;
      }

      // Advance travelling pulse particles along AI great-circle arcs
      if (aiCurves.length > 0) {
        for (let i = 0; i < aiCurves.length; i++) {
          arcProgress[i] = (arcProgress[i] + arcSpeeds[i]) % 1.0;
          aiCurves[i].getPoint(arcProgress[i], _tempVec);
          arcPulsePositions[i * 3]     = _tempVec.x;
          arcPulsePositions[i * 3 + 1] = _tempVec.y;
          arcPulsePositions[i * 3 + 2] = _tempVec.z;
        }
        pulseGeo.attributes.position.needsUpdate = true;
      }

      globeRenderer.render(globeScene, globeCamera);
      globeAnimFrameId = requestAnimationFrame(animateGlobe);
    }

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        if (pauseGlobeAnimation) pauseGlobeAnimation();
      } else {
        if (resumeGlobeAnimation) resumeGlobeAnimation();
      }
    });

    // Cycle active planetary defense stations in HUD
    let stationIdx = 0;
    setInterval(() => {
      if (document.hidden || !isGlobeVisible) return;
      const el = document.getElementById('globe-active-station');
      if (el && WORLD_STATIONS.length) {
        const st1 = WORLD_STATIONS[stationIdx % WORLD_STATIONS.length];
        const st2 = WORLD_STATIONS[(stationIdx + 1) % WORLD_STATIONS.length];
        const st3 = WORLD_STATIONS[(stationIdx + 2) % WORLD_STATIONS.length];
        el.innerHTML = `${st1.flag} ${st1.name} • ${st2.flag} ${st2.name} • ${st3.flag} ${st3.name}`;
        stationIdx = (stationIdx + 1) % WORLD_STATIONS.length;
      }
    }, 5000);

    resumeGlobeAnimation();
  } catch (e) {
    console.warn("Three.js globe initialization gracefully skipped:", e);
    const panel = document.getElementById('globe-panel');
    if (panel) panel.classList.add('hidden');
  }
}

function toggle3DGlobe() {
  const panel = document.getElementById('globe-panel');
  const btn = document.getElementById('globe-toggle-btn');
  isGlobeVisible = !isGlobeVisible;

  if (isGlobeVisible) {
    if (!globeScene && typeof initThreeGlobe === 'function') {
      try { initThreeGlobe(); } catch (e) { console.warn("Lazy ThreeGlobe init:", e); }
    }
    if (panel) panel.classList.remove('hidden');
    if (btn) btn.classList.add('text-cyber-cyan');
    if (resumeGlobeAnimation) resumeGlobeAnimation();
  } else {
    if (panel) panel.classList.add('hidden');
    if (btn) btn.classList.remove('text-cyber-cyan');
    if (pauseGlobeAnimation) pauseGlobeAnimation();
  }
  if (typeof playBeep === 'function') playBeep('click');
}

// Global exposure
window.initThreeGlobe = initThreeGlobe;
window.toggle3DGlobe = toggle3DGlobe;
window.resumeGlobeAnimation = () => { if (resumeGlobeAnimation) resumeGlobeAnimation(); };
window.pauseGlobeAnimation = () => { if (pauseGlobeAnimation) pauseGlobeAnimation(); };
