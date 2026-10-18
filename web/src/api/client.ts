import axios from 'axios'

// Empty baseURL uses the current origin (Vite proxy in dev).
const baseURL = import.meta.env.VITE_API_BASE_URL || ''

export const api = axios.create({
  baseURL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})
