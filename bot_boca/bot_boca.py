"""
Bot para vigilar entradas de Boca (mapa de sectores) y reservar apenas se libere una.
El pago lo hacés VOS a mano.

INSTALACIÓN (una sola vez, en la terminal):
    pip install playwright
    playwright install chromium

USO NORMAL:
    python bot_boca.py

La primera vez se abre un navegador: iniciá sesión, pasá la cola si hay,
y llegá hasta la pantalla "ELEGÍ EL SECTOR" (el mapa del estadio).
Después volvé a la terminal y apretá ENTER. Tu sesión queda guardada.

SI NO DETECTA LOS SECTORES VERDES:
    python bot_boca.py diagnostico
Eso imprime lo que ve en el mapa y guarda pagina.html. Mandámelos y lo ajusto.
"""

import random
import re
import sys
import threading
import time

from playwright.sync_api import sync_playwright

# ================== CONFIGURACIÓN (cambiá esto) ==================

# Link del partido (el que usás para entrar). Después navegás a mano hasta el mapa.
URL = "https://bocasocios.bocajuniors.com.ar/matches/882/plateas"

# Carpeta donde se guarda la sesión (el login). Cada cuenta usa la suya.
# "perfil_facundo" = cuenta de Facundo; "perfil_boca" = la cuenta de Matías.
PERFIL = "perfil_facundo"

# Sectores que querés, con el nombre EXACTO que aparece en el mapa (mayúsculas da igual).
# Si la lista tiene sectores, el bot SOLO agarra esos y ignora todos los demás.
SOLO_SECTORES = [
    # Plateas altas
    "P", "I", "J", "F", "G", "H", "K",
    # Plateas medias
    "M", "MD", "MC", "MI", "CD", "CI", "AD", "AC", "AI", "BD", "BC", "BI", "DD", "DI",
]

# Sectores que NO querés (mismo criterio: nombre exacto como en el mapa).
SECTORES_NO = ["LID", "LIC", "LV", "LII", "LPD", "LPC", "LD", "LPI"]

# Textos de los botones. Si en la página dicen otra cosa, cambialos acá.
TEXTO_ACTUALIZAR = "Actualizar mapa"
TEXTO_BUSCAR = "Buscar asiento disponible"
# Botón final: aprieta el PRIMERO de estos que aparezca, una sola vez, y frena. El pago lo hacés vos.
# (El texto cambia según el partido/pantalla; por eso hay varios.)
TEXTOS_FINALES = ["Agregar platea", "Reservar platea", "Comprar platea", "Reservar", "Comprar"]

# Cada cuántos segundos actualiza el mapa (aleatorio entre estos valores).
# No lo bajes demasiado: si pedís muy seguido te pueden bloquear.
INTERVALO_MIN = 3
INTERVALO_MAX = 6

# Modo rápido: el bot mira directo el dato de disponibilidad (sin recargar el mapa).
# Cada cuántos segundos lo consulta. No lo bajes mucho, porque te pueden bloquear.
INTERVALO_API_MIN = 0.8
INTERVALO_API_MAX = 1.3

# Opcional: ventana angosta (como un celular). Si la página muestra su propio botón
# "Actualizar mapa", el bot lo usa y refresca más rápido. Probalo solo si querés.
MODO_MOVIL = False

# True = modo rápido (mira el dato directo, no recarga mientras vigila).
# False = vuelve al método de antes: recarga el mapa cada pocos segundos.
USAR_API = True

# Ruta directa: cuando la API avisa que hay lugar, va derecho a la página de asientos de ese
# sector (sin pasar por el mapa) y aprieta "Agregar platea". Si no funciona en la página,
# se apaga sola después de 2 intentos y sigue con el método de siempre.
# Qué le saca a la página para que cargue más liviana:
#   "total" = imágenes, fuentes, videos y todos los rastreadores/publicidad (recomendado)
#   "normal" = solo imágenes, fuentes, videos y algunos rastreadores
#   "nada"  = no bloquea nada (probá esto si los asientos no terminan de cargar)
BLOQUEO = "total"
# Reserva directa por la API: cuando avisa que hay lugar, pide el asiento al servidor sin
# abrir pantallas (mucho más rápido). Si falla, sigue con el método de clics de siempre.
USAR_RESERVA_API = True
# Si el servidor contesta que el asiento ya no está, NO abre las pantallas del sector (que
# cargan lentas y en gris): vuelve directo a vigilar. Poné False para el método de clics.
SOLO_API_SI_TOMADA = True
REFRESCAR_MAPA = True  # además de la API, recarga el mapa (F5) cada tanto
# El F5 solo mantiene viva la sesión (la detección la hace la API). Cada F5 del mapa dispara
# decenas de pedidos al servidor, así que más seguido = más riesgo de bloqueo, no más rapidez.
REFRESCO_MIN = 60       # segundos entre recargas (aleatorio entre estos dos valores)
REFRESCO_MAX = 90
USAR_URL_DIRECTA = False  # probado: la página de asientos no tiene el botón sin buscar antes

# Opcional: avisos al celular por Telegram. Dejalo vacío si no querés.
# Cómo conseguirlos (una sola vez):
#   1) En Telegram hablale a @BotFather, mandá /newbot, elegí nombre y usuario. Te da un TOKEN.
#   2) Pegá el token acá abajo, y en Telegram abrí tu bot nuevo y mandale cualquier mensaje ("hola").
#   3) En la terminal: python bot_boca.py telegram  -> te dice tu CHAT_ID y manda una prueba.
#   4) Pegá el CHAT_ID acá abajo. Listo.
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# ================================================================

# Busca en el mapa (SVG) los sectores en verde ("Disponible") y los marca.
# Toma el color verde de la leyenda de la página; si no la encuentra, adivina por color.
JS_BUSCAR_LIBRES = r"""
(args) => {
  const filtros = args.filtros;
  const excluir = args.excluir;
  const sacar = args.sacar || [];
  const norm = (c) => (c || '').replace(/\s+/g, '');
  let colorLibre = null;
  for (const el of document.querySelectorAll('body *')) {
    if (el.children.length !== 0) continue;
    if (!/^\s*disponible\s*$/i.test(el.textContent || '')) continue;
    const padre = el.parentElement;
    if (!padre) continue;
    for (const otro of padre.querySelectorAll('*')) {
      if (otro === el) continue;
      const cs = getComputedStyle(otro);
      for (const c of [cs.backgroundColor, cs.fill]) {
        const n = norm(c);
        if (n && n !== 'none' && n !== 'rgba(0,0,0,0)' && n !== 'rgb(0,0,0)') { colorLibre = n; break; }
      }
      if (colorLibre) break;
    }
    if (colorLibre) break;
  }
  const esVerde = (c) => {
    const m = c.match(/rgba?\((\d+),(\d+),(\d+)/);
    if (!m) return false;
    const r = +m[1], g = +m[2], b = +m[3];
    return g > r + 25 && g > b + 25;
  };
  // Letras/nombres dibujados en el mapa, con su centro en pantalla (para saber de qué sector es cada forma)
  const textos = [];
  if (filtros.length || sacar.length || args.listar) {
    for (const s of document.querySelectorAll('svg')) {
      for (const t of s.querySelectorAll('text')) {
        const txt = (t.textContent || '').trim();
        if (!txt) continue;
        const rb = t.getBoundingClientRect();
        textos.push({ txt: txt, x: rb.left + rb.width / 2, y: rb.top + rb.height / 2 });
      }
    }
  }
  const dentro = (f, x, y) => {
    try {
      if (typeof f.isPointInFill !== 'function') return false;
      const m = f.getScreenCTM();
      if (!m) return false;
      const pt = f.ownerSVGElement.createSVGPoint();
      pt.x = x;
      pt.y = y;
      return f.isPointInFill(pt.matrixTransform(m.inverse()));
    } catch (e) {
      return false;
    }
  };
  const nombresDe = (f) => {
    const out = [];
    for (const t of textos) if (dentro(f, t.x, t.y)) out.push(t.txt);
    let el = f;
    for (let i = 0; i < 3 && el && el.tagName && el.tagName.toLowerCase() !== 'svg'; i++) {
      for (const a of ['id', 'aria-label', 'data-name', 'data-sector', 'name']) {
        const v = el.getAttribute(a);
        if (v) out.push(v);
      }
      const tt = el.querySelector(':scope > title');
      if (tt && tt.textContent) out.push(tt.textContent.trim());
      el = el.parentElement;
    }
    return out;
  };
  const coincide = (nombres, filtros) => {
    for (const n of nombres) {
      const s = n.trim().toLowerCase().replace(/\s+/g, ' ').replace(/º/g, '°');
      const piezas = [s].concat(s.split(/[^a-z0-9°áéíóúñ]+/).filter(Boolean));
      if (piezas.some((p) => filtros.includes(p))) return true;
    }
    return false;
  };
  document.querySelectorAll('[data-bot-libre]').forEach((e) => e.removeAttribute('data-bot-libre'));
  const items = [];
  const descartados = [];
  for (const svg of document.querySelectorAll('svg')) {
    const rs = svg.getBoundingClientRect();
    const areaSvg = rs.width * rs.height;
    if (areaSvg < 40000) continue;
    for (const f of svg.querySelectorAll('path, polygon, rect, circle, ellipse')) {
      const fill = norm(getComputedStyle(f).fill);
      if (!fill || fill === 'none') continue;
      const r = f.getBoundingClientRect();
      const exacto = colorLibre && fill === colorLibre;
      const parecido = esVerde(fill) && !excluir.includes(fill) && r.width * r.height <= areaSvg * 0.08;
      if (!exacto && !parecido) continue;
      if (r.width < 8 || r.height < 8) continue;
      const partes = [];
      let el = f;
      for (let i = 0; i < 3 && el && el !== svg; i++) {
        partes.push(el.id, el.getAttribute('aria-label'), el.getAttribute('data-name'),
                    el.getAttribute('data-sector'), el.getAttribute('name'), el.getAttribute('class'));
        const t = el.querySelector(':scope > title');
        if (t) partes.push(t.textContent);
        el = el.parentElement;
      }
      const nombres = nombresDe(f);
      const etiqueta = (nombres.join(' / ') || partes.filter(Boolean).join(' ')).trim();
      if ((filtros.length && !coincide(nombres, filtros)) || (sacar.length && coincide(nombres, sacar))) {
        descartados.push(etiqueta || '(sin nombre)');
        continue;
      }
      f.setAttribute('data-bot-libre', String(items.length));
      items.push(etiqueta || '(sin nombre)');
    }
  }
  const conocidos = [];
  if (args.listar) {
    const vistos = new Set();
    for (const svg of document.querySelectorAll('svg')) {
      const rs = svg.getBoundingClientRect();
      const areaSvg = rs.width * rs.height;
      if (areaSvg < 40000) continue;
      for (const f of svg.querySelectorAll('path, polygon, rect, circle, ellipse')) {
        const r = f.getBoundingClientRect();
        if (r.width * r.height > areaSvg * 0.08) continue;
        const n = nombresDe(f).filter((x) => x.length <= 20).slice(0, 3).join('/');
        if (n && !vistos.has(n)) { vistos.add(n); conocidos.push(n); }
      }
    }
  }
  return { color: colorLibre, items: items, conocidos: conocidos, descartados: descartados };
}
"""

JS_DIAGNOSTICO = r"""
() => {
  const cuenta = {};
  let svgs = 0;
  for (const svg of document.querySelectorAll('svg')) {
    const r = svg.getBoundingClientRect();
    if (r.width * r.height < 40000) continue;
    svgs++;
    for (const f of svg.querySelectorAll('path, polygon, rect, circle, ellipse')) {
      const fill = (getComputedStyle(f).fill || '').replace(/\s+/g, '');
      cuenta[fill] = (cuenta[fill] || 0) + 1;
    }
  }
  return { svgs: svgs, cuenta: cuenta };
}
"""


# Dice si el mapa del estadio está en pantalla.
JS_HAY_MAPA = r"""
() => Array.from(document.querySelectorAll('svg')).some((s) => {
  const r = s.getBoundingClientRect();
  return r.width * r.height >= 40000;
})
"""

# Secuencia rápida: sector -> "Buscar asiento" -> botones finales, todo adentro de la página
# (sin idas y vueltas con Python), revisando cada 5 ms.
JS_RESERVA_RAPIDA = r"""
async (cfg) => {
  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
  const visible = (e) => !!(e.offsetParent || (e.getClientRects && e.getClientRects().length));
  const buscarBoton = (texto, estricto) => {
    const t = texto.toLowerCase();
    const selector = estricto
      ? 'button, [role=button], input[type=button], input[type=submit]'
      : 'button, a, [role=button], input[type=button], input[type=submit]';
    for (const e of document.querySelectorAll(selector)) {
      if (e.disabled || e.getAttribute('aria-disabled') === 'true') continue;
      if (estricto && e.closest('nav, header')) continue;
      const txt = ((e.innerText || e.value || e.getAttribute('aria-label') || '') + '').trim().toLowerCase();
      if (txt && txt.includes(t) && visible(e)) return e;
    }
    return null;
  };
  const esperar = async (fn, ms) => {
    const t0 = performance.now();
    while (performance.now() - t0 < ms) {
      const v = fn();
      if (v) return v;
      await dormir(5);
    }
    return null;
  };
  const sector = document.querySelector('[data-bot-libre="' + cfg.indice + '"]');
  if (!sector) return { ok: false, paso: 'sin_sector' };
  for (const tipo of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
    const Ev = tipo.startsWith('pointer') ? PointerEvent : MouseEvent;
    sector.dispatchEvent(new Ev(tipo, { bubbles: true, cancelable: true, view: window }));
  }
  const buscar = await esperar(() => buscarBoton(cfg.buscar, false), cfg.esperaBuscarMs);
  if (!buscar) return { ok: false, paso: 'buscar' };
  buscar.click();
  const apretados = [];
  const textoPagina = () => (document.body.innerText || '').toLowerCase();
  let vacioAntes = false;
  const limite = performance.now() + cfg.esperaFinalMs;
  while (performance.now() < limite && !apretados.length) {
    for (const t of cfg.finales) {
      const b = buscarBoton(t, true);
      if (b) {
        vacioAntes = /a[uú]n no agregaste/.test(textoPagina());
        b.click();
        apretados.push(t);
        break;  // alternativas: con uno alcanza
      }
    }
    if (/ya no est[aá] disponible/.test(textoPagina())) break;
    await dormir(5);
  }
  if (!apretados.length) return { ok: false, paso: 'finales', apretados: apretados };

  // Verificar si realmente se agregó, o si la página avisó que ya no estaba disponible
  let resultado = 'incierto';
  const t0 = performance.now();
  while (performance.now() - t0 < cfg.verificarMs) {
    const txt = textoPagina();
    if (/ya no est[aá] disponible/.test(txt)) { resultado = 'agotada'; break; }
    if (vacioAntes && !/a[uú]n no agregaste/.test(txt)) { resultado = 'agregada'; break; }
    await dormir(20);
  }
  if (resultado === 'agotada') {
    const volver = buscarBoton('volver al mapa', true);
    if (volver) volver.click();
    return { ok: false, paso: 'agotada', apretados: apretados };
  }
  return { ok: true, paso: 'listo', resultado: resultado, apretados: apretados };
}
"""

# Ruta directa: ya estamos en la página de asientos del sector; apretar "Agregar platea" y verificar.
JS_RESERVA_DIRECTA = r"""
async (cfg) => {
  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
  const visible = (e) => !!(e.offsetParent || (e.getClientRects && e.getClientRects().length));
  const textoPagina = () => (document.body.innerText || '').toLowerCase();
  const buscarBoton = (texto) => {
    const t = texto.toLowerCase();
    for (const e of document.querySelectorAll('button, [role=button], input[type=button], input[type=submit]')) {
      if (e.disabled || e.getAttribute('aria-disabled') === 'true') continue;
      if (e.closest('nav, header')) continue;
      const txt = ((e.innerText || e.value || e.getAttribute('aria-label') || '') + '').trim().toLowerCase();
      if (txt && txt.includes(t) && visible(e)) return e;
    }
    return null;
  };
  let boton = null;
  const t0 = performance.now();
  while (performance.now() - t0 < cfg.esperaMs) {
    for (const t of cfg.finales) {
      boton = buscarBoton(t);
      if (boton) break;
    }
    if (boton) break;
    if (/ya no est[aá] disponible/.test(textoPagina())) return { ok: false, paso: 'agotada' };
    await dormir(5);
  }
  if (!boton) return { ok: false, paso: 'sin_boton', url: location.pathname };
  const vacioAntes = /a[uú]n no agregaste/.test(textoPagina());
  boton.click();
  let resultado = 'incierto';
  const t1 = performance.now();
  while (performance.now() - t1 < cfg.verificarMs) {
    const txt = textoPagina();
    if (/ya no est[aá] disponible/.test(txt)) { resultado = 'agotada'; break; }
    if (vacioAntes && !/a[uú]n no agregaste/.test(txt)) { resultado = 'agregada'; break; }
    await dormir(20);
  }
  if (resultado === 'agotada') return { ok: false, paso: 'agotada' };
  return { ok: true, paso: 'listo', resultado: resultado };
}
"""

# Reserva directa por la API (lo mismo que hace la página, pero sin pantallas ni clics):
#   1) GET  /event/seat/section/<sector>/availability -> asientos libres del sector
#   2) POST /event/seat/reserve/<asiento>  {"eventoUbicacionNid": <asiento>}
#   3) GET  /member/shoppingCart/<partido> -> comprueba que quedó en el carrito
JS_RESERVA_API = r"""
async (cfg) => {
  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
  const intentos = [];
  const probados = new Set();
  // Si la página se recargó, no sabemos qué modo de cookies acepta el servidor: probamos los dos.
  const pedir = async (url, opciones) => {
    const orden = window.__credApi === 'omit' ? ['omit', 'include'] : ['include', 'omit'];
    let fallo = null;
    for (const cred of orden) {
      try {
        const r = await fetch(url, Object.assign({ credentials: cred, cache: 'no-store' }, opciones));
        window.__credApi = cred;
        let cuerpo = null;
        try { cuerpo = await r.json(); } catch (e) {}
        return { estado: r.status, ok: r.ok, cuerpo: cuerpo };
      } catch (e) {
        fallo = e;  // "Failed to fetch": el pedido ni salió, así que es seguro probar el otro modo
      }
    }
    throw fallo;
  };
  for (let ronda = 0; ronda < cfg.rondas; ronda++) {
    let lista = [];
    try {
      const r = await pedir(cfg.base + '/event/seat/section/' + cfg.seccion + '/availability',
                            { method: 'GET', headers: cfg.headers });
      if (r.estado === 403 || r.estado === 429) return { ok: false, paso: 'bloqueado', estado: r.estado, intentos: intentos };
      lista = ((r.cuerpo && r.cuerpo.ubicaciones) || []).map((u) => u.nid);
    } catch (e) {
      intentos.push({ error: String(e).slice(0, 60) });
    }
    // Asientos "fantasma": la lista del sector los muestra libres pero ya no lo están.
    // Se recuerdan un rato para no gastar pedidos en ellos y probar enseguida los nuevos.
    window.__fantasmas = window.__fantasmas || {};
    const ahora = Date.now();
    for (const k of Object.keys(window.__fantasmas)) {
      if (ahora - window.__fantasmas[k] > cfg.olvidarFantasmaMs) delete window.__fantasmas[k];
    }
    const nuevos = lista.filter((n) => !probados.has(n) && !window.__fantasmas[n]).slice(0, cfg.maxAsientos);
    if (!nuevos.length && lista.length) intentos.push({ fantasmas: lista.slice(0, 5) });
    for (const nid of nuevos) {
      probados.add(nid);
      // Asiento nuevo: POST directo, sin chequeo previo (es el mismo pedido que hace la
      // página al apretar "Agregar platea"; si ya no está, contesta 500 y lo anotamos).
      try {
        const r = await pedir(cfg.base + '/event/seat/reserve/' + nid, {
          method: 'POST',
          headers: Object.assign({}, cfg.headers, { 'content-type': 'application/json' }),
          body: JSON.stringify({ eventoUbicacionNid: nid }),
        });
        const cod = r.cuerpo && r.cuerpo.codigo;
        const msg = r.cuerpo && (r.cuerpo.descripcion || r.cuerpo.mensaje || r.cuerpo.message || r.cuerpo.error);
        intentos.push({ asiento: nid, estado: r.estado, cod: cod || null, msg: msg ? String(msg).slice(0, 120) : null,
                        cuerpo: r.ok ? undefined : JSON.stringify(r.cuerpo || null).slice(0, 200) });
        if (r.estado === 403 || r.estado === 429) return { ok: false, paso: 'bloqueado', estado: r.estado, intentos: intentos };
        if (r.estado >= 400) window.__fantasmas[nid] = Date.now();
        if (r.ok) {
          let carrito = null;
          try {
            const c = await pedir(cfg.carrito, { method: 'GET', headers: cfg.headers });
            carrito = !!(c.cuerpo && c.cuerpo.items && c.cuerpo.items.length);
          } catch (e) {}
          if (carrito === false) {
            // El servidor dijo "ok" pero la platea NO quedó en el carrito: no es una reserva.
            // Anotamos qué contestó y probamos el siguiente asiento.
            intentos.push({
              asiento: nid, estado: r.estado, cod: 'ok_pero_carrito_vacio',
              cuerpo: JSON.stringify(r.cuerpo || null).slice(0, 200),
            });
            continue;
          }
          return { ok: true, paso: 'reservado', asiento: nid, enCarrito: carrito, intentos: intentos };
        }
      } catch (e) {
        intentos.push({ asiento: nid, error: String(e).slice(0, 60) });
      }
    }
    if (ronda < cfg.rondas - 1) await dormir(cfg.pausaMs);
  }
  return { ok: false, paso: 'agotada', intentos: intentos };
}
"""

# Revisa UN asiento "fantasma" (está en el carrito de otro). Si se liberó, lo reserva al toque.
#   1) GET  /event/seat/location/<asiento>/availability -> disponible: true/false
#   2) POST /event/seat/reserve/<asiento>   (solo si está disponible)
#   3) GET  /member/shoppingCart/<partido>  -> comprueba que quedó en el carrito
JS_REVISAR_FANTASMA = r"""
async (cfg) => {
  const pedir = async (url, opciones) => {
    const orden = window.__credApi === 'omit' ? ['omit', 'include'] : ['include', 'omit'];
    let fallo = null;
    for (const cred of orden) {
      try {
        const r = await fetch(url, Object.assign({ credentials: cred, cache: 'no-store' }, opciones));
        window.__credApi = cred;
        let cuerpo = null;
        try { cuerpo = await r.json(); } catch (e) {}
        return { estado: r.status, ok: r.ok, cuerpo: cuerpo };
      } catch (e) { fallo = e; }
    }
    throw fallo;
  };
  try {
    const v = await pedir(cfg.base + '/event/seat/location/' + cfg.nid + '/availability',
                          { method: 'GET', headers: cfg.headers });
    if (v.estado === 403 || v.estado === 429) return { ok: false, paso: 'bloqueado', estado: v.estado };
    const disp = v.cuerpo && v.cuerpo.ubicacion && v.cuerpo.ubicacion.disponible;
    if (!v.ok || disp !== true) return { ok: false, paso: 'sigue_tomado', estado: v.estado };
    const r = await pedir(cfg.base + '/event/seat/reserve/' + cfg.nid, {
      method: 'POST',
      headers: Object.assign({}, cfg.headers, { 'content-type': 'application/json' }),
      body: JSON.stringify({ eventoUbicacionNid: cfg.nid }),
    });
    if (r.estado === 403 || r.estado === 429) return { ok: false, paso: 'bloqueado', estado: r.estado };
    if (!r.ok) {
      const msg = r.cuerpo && (r.cuerpo.descripcion || r.cuerpo.codigo);
      return { ok: false, paso: 'perdido', estado: r.estado, msg: msg ? String(msg).slice(0, 80) : null };
    }
    let carrito = null;
    try {
      const c = await pedir(cfg.carrito, { method: 'GET', headers: cfg.headers });
      carrito = !!(c.cuerpo && c.cuerpo.items && c.cuerpo.items.length);
    } catch (e) {}
    if (carrito === false) return { ok: false, paso: 'ok_pero_carrito_vacio', cuerpo: JSON.stringify(r.cuerpo || null).slice(0, 200) };
    return { ok: true, paso: 'reservado', asiento: cfg.nid, enCarrito: carrito };
  } catch (e) {
    return { ok: false, paso: 'error', error: String(e).slice(0, 60) };
  }
}
"""

# Cuenta las formas del mapa (sirve para saber si ya cargaron todos los sectores).
JS_CONTAR_FORMAS = r"""
() => {
  let n = 0;
  for (const svg of document.querySelectorAll('svg')) {
    const r = svg.getBoundingClientRect();
    if (r.width * r.height < 40000) continue;
    n += svg.querySelectorAll('path, polygon, rect, circle, ellipse').length;
  }
  return n;
}
"""

# Pide la disponibilidad por sector directo al servidor, desde adentro de la página.
JS_API = r"""
async (cfg) => {
  const orden = window.__credApi === 'omit' ? ['omit', 'include'] : ['include', 'omit'];
  let ultimo = { ok: false, error: 'sin intentos' };
  for (const cred of orden) {
    try {
      const r = await fetch(cfg.url, {
        method: 'GET',
        headers: cfg.headers,
        credentials: cred,
        cache: 'no-store',
      });
      if (!r.ok) {
        ultimo = { ok: false, estado: r.status };
        continue;
      }
      const datos = await r.json();
      const secciones = datos.secciones || [];
      window.__credApi = cred;
      return {
        ok: true,
        nids: Object.fromEntries(secciones.filter((s) => s.hayDisponibilidad && s.activa !== false).map((s) => [s.codigo, s.nid])),
        todos: secciones.map((s) => s.codigo),
        libres: secciones
          .filter((s) => s.hayDisponibilidad && s.activa !== false)
          .map((s) => s.codigo),
      };
    } catch (e) {
      ultimo = { ok: false, error: String(e).slice(0, 80) };
    }
  }
  return ultimo;
}
"""

# Muestra cómo está armado el mapa: atributos de algunos sectores y etiquetas (diagnóstico).
JS_MUESTRA = r"""
() => {
  const resumen = (e) => {
    if (!e || !e.tagName) return '';
    const attrs = Array.from(e.attributes)
      .filter((a) => a.name !== 'd' && a.name !== 'points')
      .map((a) => a.name + '="' + a.value.slice(0, 40) + '"')
      .join(' ');
    return '<' + e.tagName.toLowerCase() + ' ' + attrs + '>';
  };
  const cadena = (f) => resumen(f) + '  <-  ' + resumen(f.parentElement) + '  <-  ' + resumen(f.parentElement && f.parentElement.parentElement);
  const sectores = [];
  const etiquetas = [];
  for (const svg of document.querySelectorAll('svg')) {
    const rs = svg.getBoundingClientRect();
    if (rs.width * rs.height < 40000) continue;
    for (const f of svg.querySelectorAll('path, polygon, rect')) {
      const fill = (getComputedStyle(f).fill || '').replace(/\s+/g, '');
      if (fill === 'rgb(218,224,235)') sectores.push(f);
      if (fill === 'rgb(155,162,173)') etiquetas.push(f);
    }
  }
  const salida = [];
  const paso = Math.max(1, Math.floor(sectores.length / 12));
  salida.push('--- SECTORES (' + sectores.length + ' en total, muestra) ---');
  for (let i = 0; i < sectores.length && salida.length < 14; i += paso) salida.push(cadena(sectores[i]));
  salida.push('--- ETIQUETAS (' + etiquetas.length + ' en total, muestra) ---');
  for (let i = 0; i < Math.min(6, etiquetas.length); i++) salida.push(cadena(etiquetas[i]));
  return salida;
}
"""

# Lista los botones y links visibles (sirve para el diagnóstico).
JS_BOTONES = r"""
() => Array.from(document.querySelectorAll('button, a, [role=button]'))
  .filter((e) => e.offsetParent !== null)
  .map((e) => (e.innerText || e.getAttribute('aria-label') || '').trim())
  .filter((t) => t)
  .slice(0, 30)
"""

# Lee los verdes que ya hay en el mapa al empezar (la cancha), para ignorarlos.
JS_VERDES_BASE = r"""
() => {
  const norm = (c) => (c || '').replace(/\s+/g, '');
  const out = new Set();
  for (const svg of document.querySelectorAll('svg')) {
    const rs = svg.getBoundingClientRect();
    if (rs.width * rs.height < 40000) continue;
    for (const f of svg.querySelectorAll('path, polygon, rect, circle, ellipse')) {
      const fill = norm(getComputedStyle(f).fill);
      const m = fill.match(/rgba?\((\d+),(\d+),(\d+)/);
      if (!m) continue;
      const r = +m[1], g = +m[2], b = +m[3];
      if (g > r + 25 && g > b + 25) out.add(fill);
    }
  }
  return Array.from(out);
}
"""

EXCLUIR = []  # uso interno: verdes de la cancha, se completa solo al arrancar
FORMAS_BASE = [0]  # uso interno: cuántas formas tiene el mapa completo
DESCARTADOS_VISTOS = set()  # uso interno: para avisar una sola vez por sector
URL_MAPA = [None]  # uso interno: la pantalla del mapa (donde apretaste ENTER)


ULTIMA_RESERVA = {}  # datos de la última reserva hecha (sector, asiento), para el aviso


def telegram(metodo, **datos):
    """Llama a la API de Telegram. Devuelve el JSON de respuesta o None si falló."""
    import json
    import urllib.parse
    import urllib.request

    try:
        cuerpo = urllib.parse.urlencode(datos).encode() if datos else None
        with urllib.request.urlopen(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{metodo}", cuerpo, timeout=10
        ) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  (Telegram {metodo}: {str(e)[:80]})")
        return None


def mandar_telegram(texto):
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        return False
    r = telegram("sendMessage", chat_id=TELEGRAM_CHAT_ID, text=texto, disable_web_page_preview="true")
    return bool(r and r.get("ok"))


def avisar(mensaje):
    print(f"\n*** {mensaje} ***\n")
    try:
        import winsound  # solo Windows
        for _ in range(5):
            winsound.Beep(1200, 400)
    except Exception:
        print("\a")
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        texto = mensaje
        if ULTIMA_RESERVA:
            texto = (
                "🟢🚨 ¡PLATEA EN TU CARRITO, LISTA PARA PAGAR!\n\n"
                f"🏟 Sector: {ULTIMA_RESERVA.get('sector', '?')}\n"
                f"💺 Asiento: {ULTIMA_RESERVA.get('asiento', '?')}\n\n"
                f"💳 Link para pagar:\n{URL_MAPA[0] or URL}\n"
                "👉 Abrí el link, andá al carrito, tocá CONTINUAR y pagá.\n"
                "⏳ El carrito tiene tiempo límite: hacelo ya.\n\n"
                "El bot dejó la pestaña quieta y no busca más hasta que apretes ENTER en la PC."
            )
        if not mandar_telegram(texto):
            print("  No pude mandar el aviso por Telegram.")


def configurar_telegram():
    """Modo 'telegram': averigua tu chat ID y manda un mensaje de prueba."""
    if not TELEGRAM_TOKEN:
        print("Primero pegá el TELEGRAM_TOKEN arriba del archivo (te lo da @BotFather con /newbot).")
        return
    yo = telegram("getMe")
    if not (yo and yo.get("ok")):
        print("El token no funciona. Revisá que lo hayas copiado entero, sin espacios.")
        return
    usuario = yo["result"].get("username")
    print(f"Bot OK: @{usuario}")
    chat_id = TELEGRAM_CHAT_ID
    if not chat_id:
        r = telegram("getUpdates")
        ids = []
        for u in (r or {}).get("result", []):
            m = u.get("message") or u.get("edited_message") or {}
            c = (m.get("chat") or {}).get("id")
            if c and c not in ids:
                ids.append(c)
        if not ids:
            print(f"No veo mensajes todavía. Abrí Telegram, buscá @{usuario}, mandale 'hola' y volvé a correr esto.")
            return
        chat_id = str(ids[-1])
        print(f"Tu CHAT_ID es: {chat_id}   -> pegalo en TELEGRAM_CHAT_ID arriba del archivo.")
    r = telegram("sendMessage", chat_id=chat_id, text="✅ Prueba del bot de Boca: los avisos van a llegar acá.")
    if r and r.get("ok"):
        print("Te mandé un mensaje de prueba. Si te llegó, ya está todo listo.")
    else:
        print("No pude mandar el mensaje de prueba. Revisá el CHAT_ID.")


def buscar_boton(page, texto):
    """Devuelve el botón con ese texto si está visible y habilitado, o None."""
    patron = re.compile(texto, re.IGNORECASE)
    for candidato in (
        page.get_by_role("button", name=patron),
        page.get_by_role("link", name=patron),
        page.get_by_text(patron),
    ):
        try:
            if candidato.count() > 0:
                primero = candidato.first
                if primero.is_visible() and primero.is_enabled():
                    return primero
        except Exception:
            continue
    return None


def hay_mapa(page):
    try:
        return bool(page.evaluate(JS_HAY_MAPA))
    except Exception:
        return False


def buscar_boton_estricto(page, texto):
    """Como buscar_boton, pero solo botones de verdad (no links del menú)."""
    patron = re.compile(texto, re.IGNORECASE)
    try:
        candidatos = page.locator(
            "button, [role=button], input[type=button], input[type=submit]"
        ).filter(has_text=patron)
        if candidatos.count() > 0:
            primero = candidatos.first
            if primero.is_visible() and primero.is_enabled():
                return primero
    except Exception:
        pass
    return None


def pulsar_finales(page, espera_inicial=4.0, espera_extra=1.2):
    """Aprieta el primer botón final que aparezca (Agregar / Reservar / Comprar platea)."""
    limite = time.time() + espera_inicial
    while time.time() < limite:
        for texto in TEXTOS_FINALES:
            boton = buscar_boton_estricto(page, texto)
            if boton is not None:
                try:
                    boton.click(timeout=2000)
                    print(f"  Apreté '{texto}'.")
                    return True
                except Exception:
                    pass
        page.wait_for_timeout(50)
    return False


def completar_reserva(page):
    """Sigue desde la pantalla en que esté: 'Buscar asiento' (si aparece) y los botones finales."""
    buscar = esperar_boton(page, TEXTO_BUSCAR, 800)
    if buscar is not None:
        try:
            buscar.click(timeout=3000)
        except Exception:
            return False
    return pulsar_finales(page, 3.0)


def esperar_boton(page, texto, timeout_ms):
    """Espera hasta timeout_ms a que aparezca el botón; revisa cada ~50 ms."""
    limite = time.time() + timeout_ms / 1000
    while time.time() < limite:
        boton = buscar_boton(page, texto)
        if boton is not None:
            return boton
        page.wait_for_timeout(50)
    return None


def mapa_cargado(page):
    """True si el mapa ya tiene (casi) todos sus sectores dibujados."""
    try:
        n = page.evaluate(JS_CONTAR_FORMAS)
    except Exception:
        return False
    base = FORMAS_BASE[0]
    return n >= base * 0.9 if base else n > 0


def esperar_mapa(page, timeout_ms):
    """Espera hasta timeout_ms a que el mapa termine de cargar; revisa cada ~100 ms."""
    limite = time.time() + timeout_ms / 1000
    while time.time() < limite:
        if mapa_cargado(page):
            return True
        page.wait_for_timeout(100)
    return False


def volver_al_mapa(page):
    if buscar_boton(page, TEXTO_ACTUALIZAR) is not None:
        return
    try:
        page.go_back(wait_until="domcontentloaded")
    except Exception:
        pass
    page.wait_for_timeout(800)


def _intentar_reservar(page):
    """
    Flujo: sector en verde -> 'Buscar asiento disponible' -> 'Confirmar'.
    Devuelve True si llegó hasta confirmar el asiento.
    """
    filtros = [a_id(s) for s in SOLO_SECTORES]
    sacar = [a_id(s) for s in SECTORES_NO]
    for i in range(6):  # prueba hasta 6 sectores verdes por vuelta
        info = page.evaluate(
            JS_BUSCAR_LIBRES, {"filtros": filtros, "excluir": EXCLUIR, "sacar": sacar}
        )
        descartados = info.get("descartados", [])
        if descartados:
            nuevos = [n for n in descartados if n not in DESCARTADOS_VISTOS]
            if nuevos:
                print(f"  Verde pero fuera de tu lista: {nuevos}")
                DESCARTADOS_VISTOS.update(nuevos)
        else:
            DESCARTADOS_VISTOS.clear()
        if i >= len(info["items"]):
            return False
        print(f"  Sector en verde: {info['items'][i]}")
        ULTIMA_RESERVA.update({"sector": info["items"][i], "asiento": "(ver carrito)"})
        loc = page.locator(f'[data-bot-libre="{i}"]')

        # Ruta rápida: todo el recorrido adentro de la página, sin pausas
        try:
            r = page.evaluate(
                JS_RESERVA_RAPIDA,
                {
                    "indice": i,
                    "buscar": TEXTO_BUSCAR,
                    "finales": TEXTOS_FINALES,
                    "esperaBuscarMs": 1500,
                    "esperaFinalMs": 4000,
                    "esperaExtraMs": 1200,
                    "verificarMs": 2000,
                },
            )
            print(f"  Resultado de la ruta rápida: {r}")
            if r.get("paso") == "agotada":
                print("  Se agotó justo al agregarla. Vuelvo al mapa y reintento.")
                page.wait_for_timeout(300)
                return False
            if r.get("ok"):
                return True
            if r.get("paso") == "finales":
                # Ya apretó "Buscar asiento" pero no vio el botón final: le damos otra chance
                if pulsar_finales(page, 3.0):
                    return True
                print("  No apareció ningún botón final (Agregar/Reservar/Comprar platea).")
                try:
                    print("  Botones que veo:", page.evaluate(JS_BOTONES))
                except Exception:
                    pass
                volver_al_mapa(page)
                return False
        except Exception as e:
            # La página cambió de pantalla en pleno clic: seguimos desde donde esté
            print(f"  (ruta rápida cortada: {str(e)[:70]})")
            if completar_reserva(page):
                return True

        for modo in ("dispatch", "click"):
            try:
                if modo == "dispatch":
                    loc.dispatch_event("click", timeout=1500)
                else:
                    loc.click(force=True, timeout=1500)
            except Exception:
                continue
            buscar = esperar_boton(page, TEXTO_BUSCAR, 1200)
            if buscar is not None:
                try:
                    buscar.click(timeout=3000)
                    pulsar_finales(page)
                    return True
                except Exception:
                    break

        print("  No apareció 'Buscar asiento': se lo llevaron o ya no hay lugar.")
        volver_al_mapa(page)
    return False


def diagnostico(page):
    base = page.evaluate(JS_VERDES_BASE)
    info = page.evaluate(
        JS_BUSCAR_LIBRES, {"filtros": [], "excluir": base, "listar": True}
    )
    resumen = page.evaluate(JS_DIAGNOSTICO)
    print("\n--- DIAGNÓSTICO ---")
    print("Mapas SVG encontrados:", resumen["svgs"])
    print("Color 'Disponible' leído de la leyenda:", info["color"])
    print("Verdes ignorados (cancha):", base)
    print("Nombres de sectores que reconozco:", info["conocidos"])
    print("\nCómo está armado el mapa:")
    for linea in page.evaluate(JS_MUESTRA):
        print("  ", linea)
    print("Botones/links visibles:", page.evaluate(JS_BOTONES))
    print("¿Encuentra 'Actualizar mapa'?", buscar_boton(page, TEXTO_ACTUALIZAR) is not None)
    print("Sectores en verde detectados:", len(info["items"]))
    for it in info["items"][:10]:
        print("   -", it)
    print("Colores en el mapa (color: cantidad de formas):")
    for color, n in resumen["cuenta"].items():
        print(f"   {color}: {n}")
    with open("pagina.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    print("Guardé pagina.html. Mandame esta salida y ese archivo.")


def norm_nombre(s):
    """Minúsculas y '°' en vez de 'º', para comparar nombres de sectores."""
    return s.lower().replace("º", "°")


# Nombre que ves en el mapa -> nombre interno que usa la página (cuando es distinto)
ALIAS_SECTORES = {
    "M": "SMV",
    "CD": "SCD", "CI": "SCI",
    "AD": "SAD", "AC": "SAC", "AI": "SAI",
    "BD": "SBD", "BC": "SBC", "BI": "SBI",
    "DD": "SDD", "DI": "SDI",
    "PALCO": "PLCOS",
}


def a_id(nombre):
    """Convierte el nombre del mapa al nombre interno de la página, en minúsculas."""
    return norm_nombre(ALIAS_SECTORES.get(nombre.strip().upper(), nombre))


def ocultar_url(url):
    """Tapa los valores largos de la URL (pueden ser tokens) antes de mostrarla."""
    from urllib.parse import parse_qsl, urlencode, urlsplit

    partes = urlsplit(url)
    consulta = [
        (k, v if len(v) <= 16 else "<oculto>") for k, v in parse_qsl(partes.query)
    ]
    return partes._replace(query=urlencode(consulta, safe="<>")).geturl()


def diagnostico_red(page):
    """Recarga el mapa y anota qué datos le pide la página al servidor."""
    respuestas = []
    pistas = ("sector", "disponib", "availab", "seat", "asiento", "platea", "stock", "zona")

    def al_responder(resp):
        try:
            if resp.request.resource_type in ("xhr", "fetch"):
                respuestas.append(resp)
        except Exception:
            pass

    page.on("response", al_responder)
    print("Recargando el mapa para ver qué datos pide la página (10 segundos)...")
    page.reload(wait_until="commit")
    page.wait_for_timeout(10000)
    page.remove_listener("response", al_responder)

    lineas = []
    for resp in respuestas:
        try:
            cuerpo = resp.text()
        except Exception:
            cuerpo = ""
        linea = f"{resp.request.method} {resp.status} {ocultar_url(resp.url)}  [{len(cuerpo)} bytes]"
        if any(p in (resp.url + cuerpo[:2000]).lower() for p in pistas):
            linea += "\n      muestra: " + cuerpo[:400].replace("\n", " ")
        lineas.append(linea)

    print("\n--- PEDIDOS DE DATOS ---")
    for linea in lineas:
        print(linea)
    with open("red.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
    print("\nGuardé red.txt. Mandame esta salida (revisala antes por si hay algo personal).")


API = {"url": None, "headers": {}}  # cómo pide la página la disponibilidad (se completa solo)


def limpiar_headers(h):
    """Deja solo los encabezados que se pueden reenviar desde la página."""
    prohibidos = {
        "host", "cookie", "origin", "referer", "content-length", "connection",
        "accept-encoding", "user-agent", "priority", "upgrade-insecure-requests",
    }
    return {
        k: v
        for k, v in h.items()
        if not k.startswith(":")
        and not k.lower().startswith("sec-")
        and k.lower() not in prohibidos
    }


def capturar_api(page):
    """Recarga una vez y copia cómo pide la página la disponibilidad de sectores."""
    pedidos = []

    def al_pedir(req):
        if "/seat/section/availability" in req.url:
            pedidos.append(req)

    page.on("request", al_pedir)
    try:
        # Ir al mapa (no solo recargar): si la pestaña quedó en la pantalla de un sector,
        # recargar ahí no pide la disponibilidad y no habría nada que copiar.
        if URL_MAPA[0] and page.url.split("?")[0].rstrip("/") != URL_MAPA[0].split("?")[0].rstrip("/"):
            page.goto(URL_MAPA[0], wait_until="commit")
        else:
            page.reload(wait_until="commit")
        esperar_mapa(page, 12000)
        page.wait_for_timeout(500)
    except Exception as e:
        print(f"  (no pude recargar el mapa para renovar la API: {str(e)[:70]})")
    finally:
        page.remove_listener("request", al_pedir)
    if not pedidos:
        return False
    req = pedidos[-1]
    API["url"] = req.url
    try:
        API["headers"] = limpiar_headers(req.all_headers())
    except Exception:
        API["headers"] = limpiar_headers(req.headers)
    return True


TRABAJO = [None]  # pestaña aparte, liviana, desde donde se vigila y se reserva (uso interno)


def pagina_api(page):
    """Pestaña desde donde se hacen los pedidos a la API (la principal si no hay otra)."""
    t = TRABAJO[0]
    try:
        if t is not None and not t.is_closed():
            return t
    except Exception:
        pass
    return page


def crear_pagina_trabajo(page):
    """Abre una pestaña liviana del mismo sitio: así los pedidos no esperan a que cargue el mapa."""
    try:
        m = re.match(r"^(https?://[^/]+)/", URL_MAPA[0] or "")
        if not m:
            return
        w = page.context.new_page()
        # /favicon.ico no sirve: es una imagen y bloquear_pesados la frena. robots.txt es texto.
        for ruta in ("/robots.txt", "/"):
            try:
                w.goto(m.group(1) + ruta, wait_until="domcontentloaded", timeout=8000)
                r = w.evaluate(JS_API, {"url": API["url"], "headers": API["headers"]})
                if r.get("ok"):
                    TRABAJO[0] = w
                    page.bring_to_front()
                    print("  Pestaña de trabajo lista: vigila aparte, sin depender de la pantalla del mapa.")
                    return
                print(f"  (pestaña de trabajo en {ruta}: la API contestó {r})")
            except Exception as e:
                print(f"  (pestaña de trabajo en {ruta}: {str(e)[:70]})")
        try:
            w.close()
        except Exception:
            pass
    except Exception:
        pass
    print("  (No pude abrir la pestaña de trabajo: uso la principal.)")
    print("  OJO: sin pestaña de trabajo, cada F5 del mapa corta la vigilancia un instante.")


ULTIMO_FALLO_API = [""]  # por qué falló la última consulta (para mostrarlo una sola vez)


def consultar_api(page):
    """Devuelve {'todos': [...], 'libres': [...]} o None si la consulta falló.

    Prueba desde la pestaña de trabajo y, si esa no puede, desde la principal."""
    motivo = ""
    for pestana in dict.fromkeys([pagina_api(page), page]):
        try:
            r = pestana.evaluate(JS_API, {"url": API["url"], "headers": API["headers"]})
        except Exception as e:
            motivo = str(e)[:70]
            continue
        if r.get("ok"):
            return r
        motivo = f"estado {r.get('estado')}" if r.get("estado") else str(r.get("error", ""))[:70]
    ULTIMO_FALLO_API[0] = motivo
    return None


def _en(lista, codigo):
    conj = {a_id(s) for s in lista} | {norm_nombre(s) for s in lista}
    return norm_nombre(str(codigo)) in conj or a_id(str(codigo)) in conj


def quiero_sector(codigo):
    """True si el código de sector que devuelve la API está en tu lista."""
    if SECTORES_NO and _en(SECTORES_NO, codigo):
        return False
    if not SOLO_SECTORES:
        return True
    return _en(SOLO_SECTORES, codigo)


def mostrar_mapa_actualizado(page, espera=3):
    """Refresca el mapa y espera a que se pinte algún sector en verde."""
    estoy_en_mapa = (
        not URL_MAPA[0]
        or page.url.split("?")[0].rstrip("/") == URL_MAPA[0].split("?")[0].rstrip("/")
    )
    boton = buscar_boton(page, TEXTO_ACTUALIZAR) if estoy_en_mapa else None
    try:
        if not estoy_en_mapa:
            page.goto(URL_MAPA[0], wait_until="commit")
        elif boton is not None:
            boton.click(timeout=2000)
        else:
            page.reload(wait_until="commit")
    except Exception:
        pass
    esperar_mapa(page, 12000)
    args = {
        "filtros": [a_id(s) for s in SOLO_SECTORES],
        "excluir": EXCLUIR,
        "sacar": [a_id(s) for s in SECTORES_NO],
    }
    limite = time.time() + espera
    while time.time() < limite:
        try:
            if page.evaluate(JS_BUSCAR_LIBRES, args)["items"]:
                return True
        except Exception:
            pass
        page.wait_for_timeout(100)
    return False


SECTOR_DE = {}  # nid del sector -> código (SMV, SBI...), para los mensajes
ENFRIADO = {}  # sector -> hasta cuándo no volver a consultarlo (solo tenía fantasmas)
ENFRIAR_SEG = 4.0  # un sector con solo fantasmas se deja descansar este tiempo
PAUSA_BLOQUEO_SEG = 25.0  # si el servidor contesta 403/429, se para este tiempo

# Asientos "fantasma": figuran en la lista del sector pero están en el carrito de otro.
# Si esa persona no paga a tiempo, el asiento se libera: por eso los vigilamos un rato.
FANTASMAS = {}  # asiento -> {"sector": código, "visto": hora en que se lo vio}
FANTASMA_OLVIDAR_SEG = 20 * 60  # cuánto tiempo vigilar un fantasma (el carrito vence antes)
FANTASMA_CADA = 3  # revisa un fantasma cada N consultas (1 pedido chico, en rueda)
_rueda_fantasma = [0]


def anotar_fantasmas(resultado, sector):
    """Guarda los asientos que el servidor rechazó (están en el carrito de otro)."""
    ahora = time.time()
    for i in resultado.get("intentos") or []:
        nids = []
        if i.get("asiento") and (i.get("fantasma") or (i.get("estado") or 0) >= 400):
            nids.append(i["asiento"])
        nids.extend(i.get("fantasmas") or [])
        for n in nids:
            if n not in FANTASMAS:
                print(f"  Asiento {n} ({sector}) está en el carrito de otro: lo vigilo por si se libera.")
            FANTASMAS[n] = {"sector": sector, "visto": ahora}


def revisar_fantasma(page):
    """Revisa el siguiente fantasma de la rueda. True si lo reservó; 'bloqueado' si nos frenaron."""
    ahora = time.time()
    for n in [k for k, v in FANTASMAS.items() if ahora - v["visto"] > FANTASMA_OLVIDAR_SEG]:
        del FANTASMAS[n]
    if not FANTASMAS or not API["url"]:
        return False
    m = re.match(r"^(https?://[^/]+)/event/(\d+)/", API["url"])
    if not m:
        return False
    base, evento = m.group(1), m.group(2)
    nids = sorted(FANTASMAS)
    nid = nids[_rueda_fantasma[0] % len(nids)]
    _rueda_fantasma[0] += 1
    try:
        r = pagina_api(page).evaluate(
            JS_REVISAR_FANTASMA,
            {"base": base, "nid": nid, "headers": API["headers"],
             "carrito": f"{base}/member/shoppingCart/{evento}"},
        )
    except Exception as e:
        print(f"  (revisión de fantasma cortada: {str(e)[:70]})")
        return False
    if r.get("ok"):
        print(f"  ¡Fantasma {nid} ({FANTASMAS[nid]['sector']}) se liberó y lo reservé!: {r}")
        ULTIMA_RESERVA.update({"sector": FANTASMAS[nid]["sector"], "asiento": nid})
        try:
            page.goto(URL_MAPA[0], wait_until="commit")
        except Exception:
            pass
        return True
    if r.get("paso") == "bloqueado":
        print(f"  El servidor te frenó ({r.get('estado')}) revisando fantasmas: paro {PAUSA_BLOQUEO_SEG:.0f} s.")
        return "bloqueado"
    if r.get("paso") in ("perdido", "ok_pero_carrito_vacio"):
        print(f"  Fantasma {nid} se liberó pero no lo pude agarrar: {r}")
    if r.get("paso") == "sigue_tomado" and r.get("estado") == 404:
        del FANTASMAS[nid]  # ya no existe para el servidor
    return False


def reserva_api(page, nids):
    """Reserva hablando directo con el servidor (mismos pedidos que hace la página)."""
    if not (USAR_RESERVA_API and nids and API["url"]):
        return False
    m = re.match(r"^(https?://[^/]+)/event/(\d+)/", API["url"])
    if not m:
        return False
    base, evento = m.group(1), m.group(2)
    tomada = False
    ahora = time.time()
    nids = [n for n in nids if ENFRIADO.get(n, 0) <= ahora]
    if not nids:
        return "tomada"  # todos en descanso: no se gasta ni un pedido
    cfg_base = {
        "base": base,
        "headers": API["headers"],
        "carrito": f"{base}/member/shoppingCart/{evento}",
        "rondas": 1,  # una sola pasada: la vigilancia ya vuelve a consultar enseguida
        "pausaMs": 120,
        "maxAsientos": 8,
        "olvidarFantasmaMs": 60000,
    }
    for nid in nids:
        r = None
        # Primero desde la pestaña de trabajo; si el pedido ni sale ("Failed to fetch"),
        # reintenta enseguida desde la pestaña principal (misma sesión, otra pestaña).
        for pestana in dict.fromkeys([pagina_api(page), page]):
            try:
                r = pestana.evaluate(JS_RESERVA_API, dict(cfg_base, seccion=nid))
            except Exception as e:
                print(f"  (reserva directa cortada: {str(e)[:70]})")
                continue
            ints = r.get("intentos") or []
            solo_errores = ints and all("error" in i and "asiento" not in i for i in ints)
            if not solo_errores:
                break
            print(f"  Reserva directa (sector {nid}) no pudo ni preguntar: {r}. Pruebo desde la otra pestaña.")
        if r is None:
            continue
        print(f"  Reserva directa (sector {nid}): {r}")
        anotar_fantasmas(r, SECTOR_DE.get(nid, nid))
        if r.get("ok"):
            ULTIMA_RESERVA.update({"sector": SECTOR_DE.get(nid, nid), "asiento": r.get("asiento")})
            try:  # mostrar el carrito en pantalla para que pagues
                page.goto(URL_MAPA[0], wait_until="commit")
            except Exception:
                pass
            return True
        if r.get("paso") == "bloqueado":
            print(f"  El servidor te frenó ({r.get('estado')}): paro {PAUSA_BLOQUEO_SEG:.0f} s para que se destrabe.")
            return "bloqueado"
        if r.get("paso") == "agotada":
            ints = r.get("intentos") or []
            # Solo cuenta como "se lo llevaron" si no quedaba ningún asiento en el sector.
            # Un 500 (error del servidor) NO es "tomada": el asiento sigue figurando libre y
            # el pedido directo no le gusta al servidor. En ese caso hay que ir por los clics.
            if not ints or all(i.get("fantasma") or "fantasmas" in i for i in ints):
                # Lista vacía, o solo asientos fantasma (figuran libres pero no lo están):
                # dejar descansar el sector para no gastar pedidos en lo mismo.
                ENFRIADO[nid] = time.time() + ENFRIAR_SEG
                tomada = True
            elif any(i.get("estado") == 500 for i in ints):
                print("  El servidor rechazó la reserva directa (500) de un asiento que decía libre: voy por el método de clics.")
                return False
            elif all(("estado" in i) for i in ints):
                tomada = True
    return "tomada" if tomada else False


proximo_f5 = [0.0]  # cuándo toca el próximo F5 (uso interno)


def refrescar_y_mirar(page):
    """Toca F5 sin esperar a que cargue (así no frena la vigilancia por la API).

    La detección la hace la API; el F5 solo mantiene la pantalla y la sesión al día.
    Se dispara desde adentro de la página y vuelve enseguida: antes, Python se quedaba
    esperando hasta 3 segundos a que la recarga arrancara, y en ese rato no vigilaba."""
    try:
        estoy_en_mapa = (
            not URL_MAPA[0]
            or page.url.split("?")[0].rstrip("/") == URL_MAPA[0].split("?")[0].rstrip("/")
        )
        if estoy_en_mapa:
            page.evaluate("() => setTimeout(() => location.reload(), 0)")
        else:
            page.evaluate(
                "(u) => setTimeout(() => { location.href = u; }, 0)", URL_MAPA[0]
            )
    except Exception:
        pass
    return False


DIRECTA = {"fallos": 0}  # si la ruta directa no sirve en esta página, se apaga sola


def reserva_directa(page, nids):
    """Va directo a la página de asientos del sector (sin pasar por el mapa) y agrega la platea."""
    if not (USAR_URL_DIRECTA and URL_MAPA[0] and nids) or DIRECTA["fallos"] >= 2:
        return False
    base = URL_MAPA[0].split("?")[0].rstrip("/")
    for nid in nids:
        try:
            page.goto(f"{base}/seats/{nid}", wait_until="commit")
            r = None
            for _ in range(40):  # la página tarda en cambiar: reintenta si el contexto se destruye
                try:
                    r = page.evaluate(
                        JS_RESERVA_DIRECTA,
                        {"finales": TEXTOS_FINALES, "esperaMs": 3500, "verificarMs": 2000},
                    )
                    break
                except Exception:
                    page.wait_for_timeout(50)
            print(f"  Ruta directa (sector {nid}): {r}")
            if not r:
                continue
            if r.get("ok"):
                DIRECTA["fallos"] = 0
                return True
            if r.get("paso") == "sin_boton":
                DIRECTA["fallos"] += 1
                if DIRECTA["fallos"] >= 2:
                    print("  La ruta directa no funciona en esta página: la apago y sigo con el método normal.")
                    return False
        except Exception as e:
            print(f"  (ruta directa cortada: {str(e)[:70]})")
    return False


def turno_fantasma(page, intento):
    """Cada FANTASMA_CADA consultas revisa un fantasma. True si reservó; 'bloqueado' si nos frenaron."""
    if not FANTASMAS or intento % FANTASMA_CADA != 0:
        return False
    res_f = revisar_fantasma(page)
    if res_f is True:
        avisar("¡RESERVA HECHA! Andá al navegador y pagá YA (el carrito tiene tiempo límite).")
        input("Cuando termines, apretá ENTER para cerrar...")
    return res_f


def bucle_api(page):
    """Vigila por la API. Devuelve True si hizo la reserva, False si hay que usar la recarga."""
    print("Vigilando por la API (rápido). Para frenar: Ctrl+C.")
    intento = 0
    fallos = 0
    renovado = False
    while True:
        intento += 1
        r = consultar_api(page)
        if r is None:
            fallos += 1
            if fallos == 3:
                print(f"  La API no responde ({ULTIMO_FALLO_API[0]}); renuevo la conexión.")
            if fallos >= 3:
                # Nunca volver al método lento, pero tampoco martillar: cada reconexión recarga
                # el mapa (decenas de pedidos). Espera cada vez más: 15 s, 30 s, 60 s... hasta 3 min.
                espera = min(15 * 2 ** max(0, (fallos - 3) // 2), 180)
                bloqueo = any(c in ULTIMO_FALLO_API[0] for c in ("403", "429"))
                if bloqueo:
                    espera = max(espera, 120)
                    print(f"  El servidor te está frenando ({ULTIMO_FALLO_API[0]}). Espero {espera} s sin pedir nada.")
                else:
                    print(f"  Espero {espera} s y vuelvo a probar.")
                time.sleep(espera)
                if not bloqueo:
                    renovado = capturar_api(page)
                    if not renovado and fallos % 5 == 0:
                        print("  Sigo sin poder leer la API. Mirá el navegador: puede estar pidiendo login, cola o captcha.")
            else:
                # Un fallo suelto suele ser el F5 cortando la consulta: reintentar enseguida.
                # (No pega al servidor: la consulta ni salió.)
                time.sleep(0.3)
            continue
        if fallos >= 3:
            print("  La API volvió. Sigo vigilando.")
        fallos = 0
        renovado = False
        quiero = [c for c in r["libres"] if quiero_sector(c)]
        if not quiero and REFRESCAR_MAPA and time.time() >= proximo_f5[0]:
            # Como antes: también recarga el mapa (F5) cada tanto y mira si hay un sector en verde
            proximo_f5[0] = time.time() + random.uniform(REFRESCO_MIN, REFRESCO_MAX)
            if refrescar_y_mirar(page):
                if intentar_reservar(page):
                    avisar("¡RESERVA HECHA! Andá al navegador y terminá la compra YA.")
                    input("Cuando termines, apretá ENTER para cerrar...")
                    return True
        if not quiero:
            if intento % 20 == 0:
                print(
                    f"Consulta {intento}: funcionando. "
                    f"Sectores con lugar ahora (en total): {r['libres'] or 'ninguno'}"
                    + (f". Fantasmas vigilados: {len(FANTASMAS)}" if FANTASMAS else "")
                )
            res_f = turno_fantasma(page, intento)
            if res_f is True:
                return True
            time.sleep(PAUSA_BLOQUEO_SEG if res_f == "bloqueado" else random.uniform(INTERVALO_API_MIN, INTERVALO_API_MAX))
            continue
        nids = [r["nids"][c] for c in quiero if c in (r.get("nids") or {})]
        for c in quiero:
            if c in (r.get("nids") or {}):
                SECTOR_DE[r["nids"][c]] = c
        if all(ENFRIADO.get(n, 0) > time.time() for n in nids):
            # Solo sectores en descanso (tenían fantasmas): no avisar de nuevo ni gastar pedidos,
            # pero sí seguir revisando los fantasmas por si uno se liberó.
            res_f = turno_fantasma(page, intento)
            if res_f is True:
                return True
            time.sleep(PAUSA_BLOQUEO_SEG if res_f == "bloqueado" else random.uniform(INTERVALO_API_MIN, INTERVALO_API_MAX))
            continue
        print(f"  ¡La API dice que hay lugar en: {quiero}!")
        res_api = reserva_api(page, nids)
        if res_api is True:
            avisar("¡RESERVA HECHA! Andá al navegador y pagá YA (el carrito tiene tiempo límite).")
            input("Cuando termines, apretá ENTER para cerrar...")
            return True
        if res_api == "bloqueado":
            # El servidor nos frenó: insistir (por API o por clics) solo empeora el bloqueo.
            time.sleep(PAUSA_BLOQUEO_SEG)
            continue
        if res_api == "tomada" and SOLO_API_SI_TOMADA:
            # Se lo llevó otro o era fantasma: seguimos vigilando sin abrir pantallas
            time.sleep(random.uniform(INTERVALO_API_MIN, INTERVALO_API_MAX))
            continue
        if reserva_directa(page, nids):
            avisar("¡RESERVA HECHA! Andá al navegador y terminá la compra YA.")
            input("Cuando termines, apretá ENTER para cerrar...")
            return True
        mostrar_mapa_actualizado(page)
        if intentar_reservar(page):
            avisar("¡RESERVA HECHA! Andá al navegador y terminá la compra YA.")
            input("Cuando termines, apretá ENTER para cerrar...")
            return True
        time.sleep(0.5)


GRABACION = []  # pedidos de la página al servidor, pendientes de anotar (se completa solo)


def grabar_pedidos(page):
    """Empieza a anotar los pedidos que hace la página al servidor (sin encabezados ni claves)."""

    def al_responder(resp):
        try:
            req = resp.request
            if req.resource_type not in ("xhr", "fetch"):
                return
            if "bocasocios-gw" not in req.url or "/seat/section/availability" in req.url:
                return
            # Ruido que no sirve (y datos personales del socio): no se anota.
            ruido = ("/queueit/validate", "/event/matches/plus",
                     "/member/season-pass", "/member/photo", "/member/profile",
                     "/strapi/", "/home/appVersion", "/payment/seasonPass")
            if any(r in req.url for r in ruido) or req.url.rstrip("/").endswith("/member"):
                return
            GRABACION.append(resp)
        except Exception:
            pass

    page.on("response", al_responder)


def volcar_grabacion():
    """Escribe en grabacion.txt lo que la página pidió, para ver cómo se reserva."""
    if not GRABACION:
        return
    pendientes = list(GRABACION)
    GRABACION.clear()
    lineas = []
    for resp in pendientes:
        try:
            req = resp.request
            hora = time.strftime("%H:%M:%S")
            envia = (req.post_data or "")[:400]
            try:
                recibe = resp.text()[:400]
            except Exception:
                recibe = "(no se pudo leer)"
            if '"items":null' in recibe.replace(" ", ""):
                continue  # carrito vacío: no aporta nada
            linea = f"[{hora}] {req.method} {resp.status} {ocultar_url(req.url)}"
            if envia:
                linea += f"\n      envía:  {envia}"
            if recibe:
                linea += f"\n      recibe: {recibe}"
            lineas.append(linea)
        except Exception:
            continue
    if lineas:
        with open("grabacion.txt", "a", encoding="utf-8") as f:
            f.write("\n".join(lineas) + "\n")
        print(f"  (Anoté {len(lineas)} pedidos en grabacion.txt)")


def intentar_reservar(page):
    """Intenta reservar y deja anotado en grabacion.txt lo que pidió la página."""
    try:
        return _intentar_reservar(page)
    finally:
        try:
            volcar_grabacion()
        except Exception:
            pass


def bloquear_pesados(contexto):
    """Hace las recargas más rápidas: no baja imágenes, fuentes ni rastreadores."""
    if BLOQUEO == "nada":
        return
    rastreadores = ("google-analytics", "googletagmanager", "doubleclick", "facebook.net",
                    "hotjar")
    if BLOQUEO == "total":
        rastreadores += (
            "fbevents", "facebook.com/tr", "clarity.ms", "tiktok", "twitter.com", "linkedin",
            "mixpanel", "segment.", "sentry", "newrelic", "nr-data", "intercom", "zendesk",
            "tawk.to", "onesignal", "appsflyer", "adsystem", "criteo", "taboola", "youtube",
            "vimeo", "ytimg", "gtag", "optimizely", "amplitude", "fullstory", "logrocket",
        )
    captcha = ("recaptcha", "captcha", "gstatic", "queue-it")
    tipos = ("image", "media", "font") + (("ping", "beacon") if BLOQUEO == "total" else ())

    def manejar(route):
        req = route.request
        url = req.url.lower()
        if any(c in url for c in captcha):
            route.continue_()
        elif req.resource_type in tipos or any(r in url for r in rastreadores):
            route.abort()
        else:
            route.continue_()

    contexto.route("**/*", manejar)


def main():
    modo_diagnostico = len(sys.argv) > 1 and sys.argv[1].lower().startswith("diag")
    modo_red = len(sys.argv) > 1 and sys.argv[1].lower().startswith("red")
    modo_grabar = len(sys.argv) > 1 and sys.argv[1].lower().startswith("grab")

    if len(sys.argv) > 1 and sys.argv[1].lower().startswith("tele"):
        configurar_telegram()  # no abre el navegador
        return

    with sync_playwright() as p:
        opciones = {"viewport": {"width": 430, "height": 900}} if MODO_MOVIL else {}
        contexto = p.chromium.launch_persistent_context(
            user_data_dir=PERFIL, headless=False, **opciones
        )
        page = contexto.pages[0] if contexto.pages else contexto.new_page()
        page.goto(URL)

        input(
            "Iniciá sesión y llegá a la pantalla 'ELEGÍ EL SECTOR' (el mapa). "
            "Cuando estés ahí, apretá ENTER para continuar... "
        )

        if modo_diagnostico:
            diagnostico(page)
            input("Apretá ENTER para cerrar...")
            contexto.close()
            return

        if modo_red:
            diagnostico_red(page)
            input("Apretá ENTER para cerrar...")
            contexto.close()
            return

        if modo_grabar:
            grabar_pedidos(page)
            print("Grabando. Ahora hacé el recorrido A MANO en el navegador del bot:")
            print("  elegí un sector, 'Buscar asiento disponible' y 'Agregar platea'.")
            listo = threading.Event()

            def esperar_enter():
                input("Cuando termines (aunque salga el cartel de que ya no está), apretá ENTER acá... ")
                listo.set()

            threading.Thread(target=esperar_enter, daemon=True).start()
            while not listo.is_set():
                page.wait_for_timeout(300)
                volcar_grabacion()
            volcar_grabacion()
            print("Listo. Mandame el archivo grabacion.txt (revisalo antes por si hay algo personal).")
            contexto.close()
            return

        # No arrancar ciego: si el mapa no está cargado, esperar a que lo esté.
        while True:
            try:
                formas = page.evaluate(JS_CONTAR_FORMAS)
            except Exception:
                formas = 0
            if formas >= 50:
                break
            print(f"  No veo el mapa cargado (solo {formas} formas; tiene que haber ~200).")
            input("  Esperá a que se dibujen los sectores (F5 si hace falta; login o cola si pide) y apretá ENTER... ")

        URL_MAPA[0] = page.url
        bloquear_pesados(contexto)
        grabar_pedidos(page)
        EXCLUIR[:] = page.evaluate(JS_VERDES_BASE)
        print("Verdes ignorados (cancha):", EXCLUIR)
        FORMAS_BASE[0] = page.evaluate(JS_CONTAR_FORMAS)
        print("Formas del mapa completo:", FORMAS_BASE[0])
        if SOLO_SECTORES or SECTORES_NO:
            info0 = page.evaluate(
                JS_BUSCAR_LIBRES, {"filtros": [], "excluir": EXCLUIR, "listar": True}
            )
            conocidos = norm_nombre(" ".join(info0["conocidos"]))
            tokens = set(re.split(r"[^a-z0-9°áéíóúñ]+", conocidos))
            faltan = [
                s
                for s in SOLO_SECTORES + SECTORES_NO
                if (a_id(s) not in tokens if " " not in s else a_id(s) not in conocidos)
            ]
            print("Sectores que busca:", SOLO_SECTORES or "TODOS")
            print("Sectores que NO quiere:", SECTORES_NO)
            if faltan:
                print(f"OJO: no reconozco estos sectores en el mapa: {faltan}.")
                print("Corré 'python bot_boca.py diagnostico' y mandame lo que imprime.")
        # Modo rápido: leer la disponibilidad directo, sin recargar el mapa
        if USAR_API and capturar_api(page):
            prueba = consultar_api(page)
            if prueba is not None:
                print("Códigos que devuelve la API:", prueba["todos"])
                faltan_api = [
                    s
                    for s in SOLO_SECTORES
                    if not any(_en([s], c) for c in prueba["todos"])
                ]
                if faltan_api:
                    print(f"OJO: la API no tiene estos sectores: {faltan_api}.")
                crear_pagina_trabajo(page)
                if bucle_api(page):
                    contexto.close()
                    return
            else:
                print("No pude leer la disponibilidad por la API.")
        else:
            print("Modo rápido apagado o no disponible.")
        print("Sigo con el método de recarga.")

        intento = 0
        proxima_recarga = time.time()
        url_mapa = page.url  # la pantalla donde estabas al apretar ENTER
        sin_mapa = 0
        print("Vigilando el mapa. Para frenar: Ctrl+C.")
        while True:
            intento += 1
            espera = 2
            try:
                actualizar = buscar_boton(page, TEXTO_ACTUALIZAR)
                if actualizar is not None:
                    # Hay botón: lo apretamos y esperamos el intervalo normal
                    actualizar.click(timeout=2000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=3000)
                    except Exception:
                        pass
                    page.wait_for_timeout(500)
                    espera = random.uniform(INTERVALO_MIN, INTERVALO_MAX)
                else:
                    # Sin botón: recargamos cada tanto y leemos el mapa entre recargas
                    espera = 0.25
                    if time.time() >= proxima_recarga:
                        page.reload(wait_until="commit")
                        esperar_mapa(page, 12000)
                        proxima_recarga = time.time() + random.uniform(
                            INTERVALO_MIN, INTERVALO_MAX
                        )

                if hay_mapa(page):
                    sin_mapa = 0
                else:
                    sin_mapa += 1
                    if sin_mapa % 20 == 0:
                        print("  No veo el mapa, vuelvo a la pantalla del mapa.")
                        try:
                            page.goto(url_mapa, wait_until="domcontentloaded")
                            page.wait_for_timeout(3000)
                        except Exception as e:
                            print(f"  No pude volver al mapa ({e}).")
                    if sin_mapa % 80 == 0:
                        avisar(
                            "Se perdió el mapa. Mirá el navegador: "
                            "puede estar pidiendo login, cola o captcha."
                        )

                if intentar_reservar(page):
                    avisar("¡RESERVA HECHA! Andá al navegador y terminá la compra YA.")
                    input("Cuando termines de pagar, apretá ENTER para cerrar...")
                    break
                if intento % 40 == 0:
                    print(f"Intento {intento}: nada disponible todavía.")
            except Exception as e:
                print(f"Intento {intento}: error ({e}). Sigo igual.")
            time.sleep(espera)

        contexto.close()


if __name__ == "__main__":
    main()
