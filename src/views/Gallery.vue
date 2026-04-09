<template>
  <div class="min-h-screen bg-[var(--paper)] text-[var(--ink)]">
    <div class="pointer-events-none fixed inset-0 opacity-70">
      <div class="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(15,23,42,0.06),transparent_38%),linear-gradient(135deg,rgba(255,255,255,0.9),rgba(245,245,244,0.96))]" />
      <div class="absolute inset-0 bg-[linear-gradient(rgba(24,24,27,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(24,24,27,0.03)_1px,transparent_1px)] bg-[size:36px_36px]" />
    </div>

    <div class="relative mx-auto max-w-7xl px-4 pb-14 pt-6 sm:px-6 lg:px-8">
      <header class="sticky top-0 z-20 mb-10 border-b border-stone-200/70 bg-[color:var(--paper-glass)] backdrop-blur-xl">
        <div class="mx-auto flex max-w-4xl flex-col items-center gap-5 px-2 py-6 text-center">
          <p class="font-['IBM_Plex_Sans','PingFang_SC','Hiragino_Sans_GB',sans-serif] text-[11px] uppercase tracking-[0.45em] text-stone-500">
            JingXia Visual Archive
          </p>

          <div class="space-y-3">
            <h1 class="font-['Noto_Serif_SC','Songti_SC','STSong',serif] text-3xl font-semibold tracking-[0.08em] text-stone-900 sm:text-4xl">
              镜匣画廊
            </h1>
            <p class="mx-auto max-w-2xl text-sm leading-7 text-stone-500 sm:text-base">
              用一枚安静的搜索框，在标签与 OCR 文字中检索每一张被归档的图像。
            </p>
          </div>

          <div class="w-full max-w-2xl">
            <label class="relative block">
              <span class="pointer-events-none absolute left-5 top-1/2 -translate-y-1/2 text-sm text-stone-400">
                搜索
              </span>
              <input
                v-model="keyword"
                type="text"
                placeholder="输入标签、物体、文字片段..."
                class="h-16 w-full rounded-full border border-stone-300/80 bg-white/90 px-20 pr-6 text-base text-stone-700 outline-none ring-0 transition duration-300 placeholder:text-stone-400 focus:border-stone-500 focus:bg-white focus:shadow-[0_0_0_6px_rgba(28,25,23,0.06)]"
              >
            </label>
          </div>

          <div class="flex flex-wrap items-center justify-center gap-3 text-xs tracking-[0.14em] text-stone-400 uppercase">
            <span>共 {{ total }} 张</span>
            <span class="h-1 w-1 rounded-full bg-stone-300" />
            <span>{{ keyword.trim() ? `检索：${keyword.trim()}` : '浏览全部' }}</span>
          </div>
        </div>
      </header>

      <section class="space-y-8">
        <div
          v-if="loading"
          class="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4"
        >
          <div
            v-for="index in 8"
            :key="index"
            class="aspect-[4/5] animate-pulse rounded-[28px] border border-stone-200/70 bg-white/70"
          />
        </div>

        <div
          v-else-if="error"
          class="mx-auto max-w-2xl rounded-[32px] border border-rose-200/70 bg-white/90 px-8 py-12 text-center shadow-[0_18px_60px_rgba(127,29,29,0.06)]"
        >
          <p class="font-['Noto_Serif_SC','Songti_SC','STSong',serif] text-2xl text-stone-900">
            画廊暂时未能展开
          </p>
          <p class="mt-4 text-sm leading-7 text-stone-500">
            {{ error }}
          </p>
        </div>

        <div
          v-else-if="images.length"
          class="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4 xl:gap-5"
        >
          <ImageCard
            v-for="image in images"
            :key="image.id || image.url || image.local_path"
            :image="image"
            @delete="handleDeleteImage"
          />
        </div>

        <div
          v-else
          class="mx-auto max-w-2xl rounded-[32px] border border-dashed border-stone-300 bg-white/75 px-8 py-16 text-center"
        >
          <p class="font-['Noto_Serif_SC','Songti_SC','STSong',serif] text-2xl text-stone-900">
            空匣
          </p>
          <p class="mt-4 text-sm leading-7 text-stone-500">
            当前没有可展示的图片，或者关键词没有命中任何标签与 OCR 文本。
          </p>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { deleteImage, fetchImages } from '../api'
import ImageCard from '../components/ImageCard.vue'

const images = ref([])
const total = ref(0)
const keyword = ref('')
const loading = ref(false)
const error = ref('')

const pageSize = 24
let debounceTimer = null
let latestRequestId = 0

async function loadImages(options = {}) {
  const requestId = ++latestRequestId
  loading.value = true
  error.value = ''

  try {
    const result = await fetchImages({
      keyword: options.keyword ?? keyword.value,
      page: 1,
      pageSize,
    })

    // 只接收最后一次请求的结果，避免快速输入时旧响应覆盖新状态。
    if (requestId !== latestRequestId) return

    images.value = result.items
    total.value = result.total
  } catch (err) {
    if (requestId !== latestRequestId) return

    console.error('Failed to load gallery images:', err)
    images.value = []
    total.value = 0
    error.value = '无法连接镜匣核心服务，请确认 http://127.0.0.1:8000/api/v1 可访问，并且已实现图片列表接口。'
  } finally {
    if (requestId === latestRequestId) {
      loading.value = false
    }
  }
}

async function handleDeleteImage(id) {
  if (!id) return

  const confirmed = window.confirm('确定要将这张图像从匣子中抹除吗？')
  if (!confirmed) return

  try {
    await deleteImage(id)
    images.value = images.value.filter((image) => image.id !== id)
    total.value = Math.max(0, total.value - 1)
  } catch (err) {
    console.error('Failed to delete image:', err)
    window.alert('删除失败，请稍后重试。')
  }
}

watch(keyword, (value) => {
  if (debounceTimer) window.clearTimeout(debounceTimer)

  debounceTimer = window.setTimeout(() => {
    loadImages({ keyword: value })
  }, 280)
})

onMounted(() => {
  loadImages()
})

onBeforeUnmount(() => {
  if (debounceTimer) window.clearTimeout(debounceTimer)
})
</script>

<style scoped>
:global(:root) {
  --paper: #f6f4ef;
  --paper-glass: rgba(246, 244, 239, 0.82);
  --ink: #1f2937;
}
</style>
