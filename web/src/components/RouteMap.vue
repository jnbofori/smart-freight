<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import type { AssignmentRoute } from '@/types'

const props = defineProps<{
  route: AssignmentRoute
  unitNumber?: string
  /** When true, use broken/OOS styling (rose polyline + marker). */
  outOfService?: boolean
}>()

const mapEl = ref<HTMLElement | null>(null)
let map: L.Map | null = null
let layer: L.LayerGroup | null = null
let resizeObserver: ResizeObserver | null = null
let lastBounds: L.LatLngBounds | null = null
const sizeTimers: number[] = []

function clearSizeTimers() {
  for (const t of sizeTimers) window.clearTimeout(t)
  sizeTimers.length = 0
}

/** Leaflet mis-sizes when the parent collapse/dialog was still animating open. */
function refreshSize() {
  if (!map) return
  map.invalidateSize({ animate: false })
  if (lastBounds && lastBounds.isValid()) {
    map.fitBounds(lastBounds, { padding: [28, 28], animate: false })
  }
}

function scheduleSizeRefresh() {
  clearSizeTimers()
  // collapse expand animation typically ~200–300ms
  for (const ms of [0, 50, 150, 350, 600]) {
    sizeTimers.push(window.setTimeout(() => refreshSize(), ms))
  }
}

function stopIcon(label: string, bg: string) {
  return L.divIcon({
    className: 'sf-map-label',
    html: `<div style="display:flex;align-items:center;justify-content:center;min-width:28px;height:28px;padding:0 6px;border-radius:9999px;background:${bg};color:#fff;font:700 11px/1 system-ui,sans-serif;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35)">${label}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  })
}

function truckIcon(broken = false) {
  const fill = broken ? '#be123c' : '#b45309'
  const ring = broken ? '#ffe4e6' : '#fef3c7'
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <rect x="1" y="7" width="13" height="8" rx="1.5" fill="${fill}" stroke="#fff" stroke-width="1.5"/>
    <path d="M14 10h4.2l2.8 3v2H14V10z" fill="${fill}" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/>
    <circle cx="6" cy="17.5" r="2" fill="#1c1917" stroke="#fff" stroke-width="1.2"/>
    <circle cx="17.5" cy="17.5" r="2" fill="#1c1917" stroke="#fff" stroke-width="1.2"/>
  </svg>`
  return L.divIcon({
    className: 'sf-map-label',
    html: `<div style="display:flex;align-items:center;justify-content:center;width:36px;height:36px;border-radius:9999px;background:${ring};border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35)">${svg}</div>`,
    iconSize: [36, 36],
    iconAnchor: [18, 18],
  })
}

function ensureMap() {
  if (!mapEl.value || map) return
  map = L.map(mapEl.value, {
    scrollWheelZoom: false,
    // Avoid wrong tile positions before first real layout
    fadeAnimation: false,
  })
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap',
    maxZoom: 19,
  }).addTo(map)
  layer = L.layerGroup().addTo(map)
}

function render() {
  if (!mapEl.value) return
  // Wait until the collapse panel has a real width before creating the map
  if (mapEl.value.clientWidth < 40) {
    return
  }
  ensureMap()
  if (!map || !layer) return

  layer.clearLayers()
  lastBounds = null

  const path = props.route.path?.length
    ? props.route.path
    : props.route.stops
        .filter((s) => s.lat != null && s.lng != null)
        .map((s) => ({ lat: s.lat as number, lng: s.lng as number }))

  const points: L.LatLngExpression[] = []

  const broken = Boolean(props.outOfService)
  const lineColor = broken ? '#be123c' : '#1d4ed8'
  const stopColor = broken ? '#9f1239' : '#1d4ed8'

  if (path.length >= 2) {
    const latlngs = path.map((p) => [p.lat, p.lng] as L.LatLngExpression)
    points.push(...latlngs)
    L.polyline(latlngs, { color: lineColor, weight: 4, opacity: 0.85 }).addTo(layer)
  }

  // Start marker under stop numbers (truck now or depot)
  if (props.route.depot_lat != null && props.route.depot_lng != null) {
    const depot: L.LatLngExpression = [props.route.depot_lat, props.route.depot_lng]
    points.push(depot)
    const atTruck = Boolean(props.route.truck_at_start)
    L.marker(depot, {
      icon: atTruck ? truckIcon(broken) : stopIcon('D', broken ? '#9f1239' : '#0f766e'),
      zIndexOffset: atTruck ? 200 : 100,
    })
      .bindPopup(
        broken
          ? `Broken / OOS: ${props.route.depot_label || 'current place'}`
          : atTruck
            ? `Truck now: ${props.route.depot_label || 'current place'}`
            : `Depot: ${props.route.depot_label || 'start'}`,
      )
      .addTo(layer)
  }

  // Numbered stops on top so they stay visible even when near the start marker
  for (const s of props.route.stops) {
    if (s.lat == null || s.lng == null) continue
    const stopNo = s.seq + 1
    const pt: L.LatLngExpression = [s.lat, s.lng]
    points.push(pt)
    L.marker(pt, {
      icon: stopIcon(String(stopNo), stopColor),
      zIndexOffset: 400 + stopNo,
    })
      .bindPopup(
        `<strong>Stop ${stopNo}</strong> · ${s.ordno}<br/>${s.destination_address || s.destination_city}`,
      )
      .addTo(layer)
  }

  if (points.length) {
    lastBounds = L.latLngBounds(points)
    map.fitBounds(lastBounds, { padding: [28, 28], animate: false })
  } else {
    map.setView([43.65, -79.38], 9)
  }

  scheduleSizeRefresh()
}

function onVisible() {
  if (!mapEl.value) return
  if (!map && mapEl.value.clientWidth >= 40) {
    render()
  } else if (map) {
    scheduleSizeRefresh()
  }
}

onMounted(() => {
  if (!mapEl.value) return
  resizeObserver = new ResizeObserver(() => onVisible())
  resizeObserver.observe(mapEl.value)
  // Also observe parent — collapse changes parent size first
  const parent = mapEl.value.parentElement
  if (parent) resizeObserver.observe(parent)
  onVisible()
})

watch(
  () => [props.route, props.outOfService],
  () => {
    if (map) render()
    else onVisible()
  },
  { deep: true },
)

onBeforeUnmount(() => {
  clearSizeTimers()
  resizeObserver?.disconnect()
  resizeObserver = null
  map?.remove()
  map = null
  layer = null
  lastBounds = null
})
</script>

<template>
  <div
    class="overflow-hidden rounded-md border"
    :class="outOfService ? 'border-rose-300' : 'border-slate-200'"
  >
    <div
      class="border-b px-3 py-1.5 text-xs"
      :class="
        outOfService
          ? 'border-rose-100 bg-rose-50 text-rose-800'
          : 'border-slate-100 bg-slate-50 text-slate-500'
      "
    >
      Route map{{ unitNumber ? ` · ${unitNumber}` : ''
      }}{{ outOfService ? ' · broken / out of service' : '' }}
    </div>
    <div ref="mapEl" class="h-64 w-full bg-slate-100" />
  </div>
</template>

<style>
/* Prevent Leaflet default icon CSS from breaking DivIcon layout */
.sf-map-label {
  background: transparent !important;
  border: none !important;
}
</style>
