<template>
  <article class="group relative overflow-hidden rounded-[28px] border border-stone-200/70 bg-white/90 shadow-[0_14px_50px_rgba(15,23,42,0.06)] transition-all duration-500 hover:-translate-y-1 hover:scale-[1.01] hover:shadow-[0_24px_70px_rgba(15,23,42,0.12)]">
    <div class="relative aspect-[4/5] overflow-hidden bg-stone-100">
      <button
        type="button"
        class="absolute right-4 top-4 z-10 flex h-10 w-10 items-center justify-center rounded-full border border-white/55 bg-white/75 text-stone-700 opacity-0 shadow-[0_10px_24px_rgba(15,23,42,0.12)] backdrop-blur-md transition-all duration-300 hover:scale-105 hover:bg-white group-hover:opacity-100"
        aria-label="删除图片"
        @click.stop="emit('delete', image.id)"
      >
        <svg
          viewBox="0 0 24 24"
          class="h-4.5 w-4.5"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M9 3h6" />
          <path d="M4 7h16" />
          <path d="M7 7l1 12h8l1-12" />
          <path d="M10 11v5" />
          <path d="M14 11v5" />
        </svg>
      </button>

      <img
        :src="image.url"
        :alt="image.ocr_text || image.filename || 'JingXia image'"
        class="h-full w-full object-cover transition-transform duration-700 group-hover:scale-[1.04]"
        loading="lazy"
      >
      <div class="absolute inset-0 bg-gradient-to-t from-stone-950/35 via-transparent to-transparent" />

      <div class="absolute left-4 top-4 rounded-full border border-white/50 bg-white/75 px-3 py-1 text-[10px] font-medium uppercase tracking-[0.28em] text-stone-700 backdrop-blur-md">
        镜匣
      </div>
    </div>

    <div class="space-y-4 px-5 py-5">
      <div class="flex flex-wrap gap-2">
        <span
          v-for="tag in safeTags"
          :key="tag"
          class="rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[11px] tracking-[0.08em] text-stone-600"
        >
          {{ tag }}
        </span>

        <span
          v-if="!safeTags.length"
          class="rounded-full border border-dashed border-stone-200 px-2.5 py-1 text-[11px] tracking-[0.08em] text-stone-400"
        >
          未提取标签
        </span>
      </div>

      <p class="ocr-preview text-sm leading-6 text-stone-600">
        {{ safeOcrText }}
      </p>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  image: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['delete'])

// 组件内部做一层兜底，避免后端字段为空时卡片布局塌陷。
const safeTags = computed(() => {
  return Array.isArray(props.image?.tags) ? props.image.tags.filter(Boolean) : []
})

const safeOcrText = computed(() => {
  return props.image?.ocr_text?.trim() || '未识别到可展示的 OCR 文本。'
})
</script>

<style scoped>
.ocr-preview {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
