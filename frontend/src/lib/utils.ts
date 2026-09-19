import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Kết hợp className từ clsx và tailwind-merge
 * - clsx: nối các className có điều kiện
 * - twMerge: loại bỏ xung đột giữa các class Tailwind (vd "px-2 px-4" -> "px-4")
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}