import axios from 'axios'

const CORE_API_BASE_URL =
  import.meta.env.VITE_CORE_API_BASE_URL || '/api/v1'

const CORE_PUBLIC_BASE_URL = CORE_API_BASE_URL.replace(/\/api\/v1\/?$/, '')

export const apiClient = axios.create({
  baseURL: CORE_API_BASE_URL,
  timeout: 15000,
})

function toAbsoluteFileUrl(rawUrl) {
  if (!rawUrl) return ''
  if (/^https?:\/\//.test(rawUrl)) return rawUrl

  const normalizedPath = rawUrl.startsWith('/') ? rawUrl : `/${rawUrl}`
  return `${CORE_PUBLIC_BASE_URL}${normalizedPath}`
}

function normalizeImage(record = {}) {
  return {
    ...record,
    url: record.url || toAbsoluteFileUrl(record.url_path),
    tags: Array.isArray(record.tags) ? record.tags : [],
    ocr_text: record.ocr_text || '',
  }
}

export async function fetchImages(params = {}) {
  const {
    keyword = '',
    page = 1,
    pageSize = 24,
  } = params

  // 约定后端提供图片列表接口；keyword 用于服务端检索 tags / OCR。
  const { data } = await apiClient.get('/images', {
    params: {
      keyword: keyword.trim() || undefined,
      page,
      page_size: pageSize,
    },
  })

  // 同时兼容两种常见返回结构：
  // 1. 直接返回数组
  // 2. 返回 { items, total, page, page_size }
  if (Array.isArray(data)) {
    return {
      items: data.map(normalizeImage),
      total: data.length,
      page,
      pageSize,
    }
  }

  const items = Array.isArray(data?.items) ? data.items.map(normalizeImage) : []

  return {
    items,
    total: Number(data?.total ?? items.length),
    page: Number(data?.page ?? page),
    pageSize: Number(data?.page_size ?? pageSize),
  }
}

export async function deleteImage(id) {
  const { data } = await apiClient.delete(`/images/${id}`)
  return data
}
