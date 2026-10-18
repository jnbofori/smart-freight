<script setup lang="ts">
import { computed } from 'vue'

import type { LoadPlacement, TruckAssignment } from '@/types'

const props = defineProps<{
  assignment: TruckAssignment
}>()

/** Display assumption: 1 skid spot ≈ 48×48 in; deck is 2 spots across */
const SPOT_IN = 48
const DECK_ACROSS = 2
const DEFAULT_HEIGHT_IN = 48

const COLORS = [
  '#2563eb',
  '#059669',
  '#d97706',
  '#dc2626',
  '#7c3aed',
  '#0891b2',
  '#ca8a04',
  '#db2777',
]

function colorForOrder(orderId: number): string {
  return COLORS[Math.abs(orderId) % COLORS.length]
}

function heightOf(p: LoadPlacement): number {
  return p.height_in != null && p.height_in > 0 ? p.height_in : DEFAULT_HEIGHT_IN
}

function footprintSpots(p: LoadPlacement): number {
  if (p.floor_spots > 0) return p.floor_spots
  return p.skid_spots > 0 ? p.skid_spots : 1
}

/** Natural depth in feet from spots on a 2-wide deck (before clamp). */
function naturalDepthFt(spots: number, linearFeet: number): number {
  if (linearFeet > 0) return linearFeet
  const rows = Math.max(1, Math.ceil(spots / DECK_ACROSS))
  return rows * (SPOT_IN / 12)
}

interface ColumnGroup {
  columnIndex: number
  spots: number
  /** True order depth before clamp (for labels) */
  trueDepthFt: number
  /** Across spots on deck (≤ 2) */
  across: number
  widthIn: number
  items: LoadPlacement[]
  totalHeightIn: number
  /** Min load_seq in column — nose=0, door=high (LIFO) */
  loadSeq: number
  /** First stop_seq (0 = first unload at door) */
  stopSeq: number
}

const columns = computed((): ColumnGroup[] => {
  const placements = props.assignment.placements ?? []
  const byCol = new Map<number, LoadPlacement[]>()
  for (const p of placements) {
    const list = byCol.get(p.column_index) ?? []
    list.push(p)
    byCol.set(p.column_index, list)
  }
  const groups: ColumnGroup[] = []
  for (const [columnIndex, items] of byCol.entries()) {
    items.sort((a, b) => a.layer - b.layer)
    const floor = items.find((i) => i.layer === 0) ?? items[0]
    const spots = footprintSpots(floor)
    const across = Math.min(Math.max(spots, 0.5), DECK_ACROSS)
    const trueDepthFt = naturalDepthFt(spots, floor.linear_feet)
    const loadSeq = Math.min(...items.map((i) => i.load_seq ?? 0))
    const stopSeq = Math.min(...items.map((i) => i.stop_seq ?? 0))
    groups.push({
      columnIndex,
      spots,
      trueDepthFt,
      across,
      widthIn: across * SPOT_IN,
      items,
      totalHeightIn: items.reduce((sum, i) => sum + heightOf(i), 0),
      loadSeq,
      stopSeq,
    })
  }
  // Nose (low load_seq) → door (high load_seq) along trailer length
  groups.sort((a, b) => a.loadSeq - b.loadSeq || a.columnIndex - b.columnIndex)
  return groups
})

/** Shared placed depths (clamped to truck length) for top + side. Door at tail. */
const placedColumns = computed(() => {
  const maxFt = Math.max(props.assignment.max_linear_feet || 1, 1)
  let cursorFt = 0
  return columns.value.map((col) => {
    const remaining = Math.max(0, maxFt - cursorFt)
    const depthFt = Math.min(col.trueDepthFt, remaining)
    const startFt = cursorFt
    cursorFt += depthFt
    return { ...col, startFt, depthFt, clipped: depthFt < col.trueDepthFt - 0.01 }
  })
})

const legend = computed(() => {
  const seen = new Map<number, { ordno: string; color: string; stacked: boolean }>()
  for (const p of props.assignment.placements ?? []) {
    if (!seen.has(p.order_id)) {
      seen.set(p.order_id, {
        ordno: p.ordno,
        color: colorForOrder(p.order_id),
        stacked: p.stacked || p.stackable,
      })
    }
  }
  return [...seen.values()]
})

// --- Top view: truck outline = true deck; skids fit inside ---
const TOP_PAD_L = 36
const TOP_PAD_R = 24
const TOP_PAD_T = 28
const TOP_PAD_B = 20

const topLayout = computed(() => {
  const maxFt = Math.max(props.assignment.max_linear_feet || 1, 1)
  const deckWidthIn = DECK_ACROSS * SPOT_IN
  const deckLengthIn = maxFt * 12

  // Uniform scale so the whole deck fits a readable panel
  const maxDrawW = 220
  const maxDrawH = 360
  const scale = Math.min(maxDrawW / deckWidthIn, maxDrawH / deckLengthIn)

  const deckW = deckWidthIn * scale
  const deckH = deckLengthIn * scale
  const deckX = TOP_PAD_L
  const deckY = TOP_PAD_T
  const svgW = deckW + TOP_PAD_L + TOP_PAD_R
  const svgH = deckH + TOP_PAD_T + TOP_PAD_B

  const blocks = placedColumns.value
    .filter((col) => col.depthFt > 0)
    .map((col) => {
      const w = Math.min(col.widthIn, deckWidthIn) * scale
      const h = col.depthFt * 12 * scale
      const x = deckX + (deckW - w) / 2
      const y = deckY + col.startFt * 12 * scale
      const floorItem = col.items[0]
      const dim =
        col.clipped
          ? `${col.widthIn}" × ${col.trueDepthFt.toFixed(1)} ft (fit ${col.depthFt.toFixed(1)})`
          : `${col.widthIn}" × ${col.trueDepthFt.toFixed(1)} ft`
      return {
        col,
        x,
        y,
        w,
        h,
        color: colorForOrder(floorItem.order_id),
      label: `#${col.stopSeq + 1} ${col.items.map((i) => i.ordno.slice(-4)).join('+')}`,
      dim,
      stacked: col.items.length > 1,
      stopSeq: col.stopSeq,
    }
  })

  return {
    svgW,
    svgH,
    deckX,
    deckY,
    deckW,
    deckH,
    deckWidthIn,
    deckLengthFt: maxFt,
    clipId: `top-deck-${props.assignment.truck_id}`,
    blocks,
  }
})

// --- Side view: outer box = truck length × max height ---
const SIDE_PAD_L = 40
const SIDE_PAD_R = 56
const SIDE_PAD_T = 24
const SIDE_PAD_B = 28

const sideLayout = computed(() => {
  const maxH = Math.max(props.assignment.max_interior_height_in || 84, 1)
  const maxFt = Math.max(props.assignment.max_linear_feet || 1, 1)
  const deckLengthIn = maxFt * 12

  const maxDrawW = 420
  const maxDrawH = 220
  const scaleX = maxDrawW / deckLengthIn
  const scaleY = maxDrawH / maxH
  // Prefer matching length/height readability; use independent scales for aspect

  const deckW = deckLengthIn * scaleX
  const deckH = maxH * scaleY
  const deckX = SIDE_PAD_L
  const deckY = SIDE_PAD_T
  const floorY = deckY + deckH
  const svgW = deckW + SIDE_PAD_L + SIDE_PAD_R
  const svgH = deckH + SIDE_PAD_T + SIDE_PAD_B

  const stacks = placedColumns.value
    .filter((col) => col.depthFt > 0)
    .map((col) => {
      const colW = Math.max(col.depthFt * 12 * scaleX, 4)
      const x = deckX + col.startFt * 12 * scaleX
      let y = floorY
      let usedH = 0
      const layers = col.items.map((item) => {
        const hIn = heightOf(item)
        // Clamp stack to interior height
        const remaining = Math.max(0, maxH - usedH)
        const drawHIn = Math.min(hIn, remaining)
        usedH += drawHIn
        const h = drawHIn * scaleY
        y -= h
        return {
          item,
          x,
          y,
          w: colW,
          h,
          hIn,
          color: colorForOrder(item.order_id),
          clipped: drawHIn < hIn - 0.01,
        }
      })
      return {
        col,
        x,
        colW,
        layers,
        totalLabel: `${Math.min(col.totalHeightIn, maxH).toFixed(0)}" / ${maxH}"`,
      }
    })

  return {
    svgW,
    svgH,
    deckX,
    deckY,
    deckW,
    deckH,
    floorY,
    maxH,
    deckLengthFt: maxFt,
    clipId: `side-deck-${props.assignment.truck_id}`,
    stacks,
  }
})
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap gap-2">
      <div
        v-for="item in legend"
        :key="item.ordno"
        class="flex items-center gap-1.5 text-xs text-slate-700"
      >
        <span
          class="inline-block h-3 w-3 rounded-sm"
          :style="{ backgroundColor: item.color }"
        />
        {{ item.ordno }}
        <span v-if="item.stacked" class="text-slate-400">(stackable)</span>
      </div>
    </div>

    <div class="grid gap-6 lg:grid-cols-2">
      <div>
        <h3 class="mb-2 text-sm font-semibold text-slate-800">Top view (floor plan)</h3>
        <div class="overflow-x-auto rounded border border-slate-200 bg-slate-50 p-2">
          <svg
            :width="topLayout.svgW"
            :height="topLayout.svgH"
            :viewBox="`0 0 ${topLayout.svgW} ${topLayout.svgH}`"
            role="img"
            aria-label="Top view of truck load"
          >
            <defs>
              <clipPath :id="topLayout.clipId">
                <rect
                  :x="topLayout.deckX"
                  :y="topLayout.deckY"
                  :width="topLayout.deckW"
                  :height="topLayout.deckH"
                />
              </clipPath>
            </defs>
            <rect
              :x="topLayout.deckX"
              :y="topLayout.deckY"
              :width="topLayout.deckW"
              :height="topLayout.deckH"
              fill="#f8fafc"
              stroke="#64748b"
              stroke-width="2"
            />
            <text
              :x="topLayout.deckX + topLayout.deckW / 2"
              :y="topLayout.deckY - 8"
              text-anchor="middle"
              class="fill-slate-500"
              font-size="11"
            >
              {{ topLayout.deckWidthIn }}" wide · {{ topLayout.deckLengthFt }} ft long
            </text>
            <text
              :x="14"
              :y="topLayout.deckY + 16"
              text-anchor="middle"
              font-size="9"
              class="fill-slate-400"
              :transform="`rotate(-90 14 ${topLayout.deckY + 16})`"
            >
              nose
            </text>
            <text
              :x="14"
              :y="topLayout.deckY + topLayout.deckH - 8"
              text-anchor="middle"
              font-size="9"
              class="fill-slate-600"
              font-weight="600"
              :transform="`rotate(-90 14 ${topLayout.deckY + topLayout.deckH - 8})`"
            >
              door / first stop
            </text>
            <g :clip-path="`url(#${topLayout.clipId})`">
              <g v-for="(b, i) in topLayout.blocks" :key="i">
                <rect
                  :x="b.x"
                  :y="b.y"
                  :width="b.w"
                  :height="b.h"
                  :fill="b.color"
                  fill-opacity="0.85"
                  stroke="#0f172a"
                  stroke-width="1"
                  rx="2"
                />
                <text
                  v-if="b.h >= 22"
                  :x="b.x + b.w / 2"
                  :y="b.y + b.h / 2 - 4"
                  text-anchor="middle"
                  font-size="10"
                  fill="#fff"
                  font-weight="600"
                >
                  {{ b.label }}
                </text>
                <text
                  v-if="b.h >= 34"
                  :x="b.x + b.w / 2"
                  :y="b.y + b.h / 2 + 10"
                  text-anchor="middle"
                  font-size="9"
                  fill="#e2e8f0"
                >
                  {{ b.dim }}{{ b.stacked ? ' · stacked' : '' }}
                </text>
              </g>
            </g>
          </svg>
        </div>
      </div>

      <div>
        <h3 class="mb-2 text-sm font-semibold text-slate-800">Side view (stack height)</h3>
        <div class="overflow-x-auto rounded border border-slate-200 bg-slate-50 p-2">
          <svg
            :width="sideLayout.svgW"
            :height="sideLayout.svgH"
            :viewBox="`0 0 ${sideLayout.svgW} ${sideLayout.svgH}`"
            role="img"
            aria-label="Side view of truck load stacks"
          >
            <defs>
              <clipPath :id="sideLayout.clipId">
                <rect
                  :x="sideLayout.deckX"
                  :y="sideLayout.deckY"
                  :width="sideLayout.deckW"
                  :height="sideLayout.deckH"
                />
              </clipPath>
            </defs>
            <rect
              :x="sideLayout.deckX"
              :y="sideLayout.deckY"
              :width="sideLayout.deckW"
              :height="sideLayout.deckH"
              fill="#f8fafc"
              stroke="#64748b"
              stroke-width="2"
            />
            <line
              :x1="sideLayout.deckX"
              :y1="sideLayout.floorY"
              :x2="sideLayout.deckX + sideLayout.deckW"
              :y2="sideLayout.floorY"
              stroke="#334155"
              stroke-width="2"
            />
            <text
              :x="sideLayout.deckX + sideLayout.deckW / 2"
              :y="sideLayout.deckY - 6"
              text-anchor="middle"
              font-size="10"
              class="fill-slate-500"
            >
              {{ sideLayout.deckLengthFt }} ft long · {{ sideLayout.maxH }}" high
            </text>
            <text
              :x="sideLayout.deckX + sideLayout.deckW + 6"
              :y="sideLayout.deckY + 10"
              font-size="10"
              class="fill-slate-500"
            >
              {{ sideLayout.maxH }}" max
            </text>
            <text
              :x="sideLayout.deckX + sideLayout.deckW + 6"
              :y="sideLayout.floorY"
              font-size="10"
              class="fill-slate-500"
            >
              floor
            </text>
            <g :clip-path="`url(#${sideLayout.clipId})`">
              <g v-for="(stack, si) in sideLayout.stacks" :key="si">
                <g v-for="(layer, li) in stack.layers" :key="li">
                  <rect
                    :x="layer.x"
                    :y="layer.y"
                    :width="layer.w"
                    :height="layer.h"
                    :fill="layer.color"
                    fill-opacity="0.9"
                    stroke="#0f172a"
                    stroke-width="1"
                  />
                  <text
                    v-if="layer.h >= 14 && layer.w >= 28"
                    :x="layer.x + layer.w / 2"
                    :y="layer.y + layer.h / 2 + 3"
                    text-anchor="middle"
                    font-size="10"
                    fill="#fff"
                    font-weight="600"
                  >
                    {{ layer.item.ordno.slice(-4) }} {{ layer.hIn }}"
                  </text>
                </g>
              </g>
            </g>
            <text
              v-for="(stack, si) in sideLayout.stacks"
              :key="`lbl-${si}`"
              :x="stack.x + stack.colW / 2"
              :y="sideLayout.floorY + 14"
              text-anchor="middle"
              font-size="9"
              class="fill-slate-600"
            >
              {{ stack.totalLabel }}
            </text>
          </svg>
        </div>
      </div>
    </div>

    <p class="text-xs text-slate-500">
      LIFO unload: stop #1 at the door (rear). Deck is {{ DECK_ACROSS }}-wide ({{ DECK_ACROSS * SPOT_IN }}");
      1 skid spot ≈ {{ SPOT_IN }}×{{ SPOT_IN }} in. Missing height defaults to
      {{ DEFAULT_HEIGHT_IN }}". Not a CAD packer.
    </p>
  </div>
</template>
