import useSWR from "swr"
import type { Account } from "@/types/account"

const fetcher = async (url: string) => {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_BASE_URL}${url}`,
    {
      credentials: "include"
    }
  )

  if (!res.ok) {
    throw new Error("Failed to fetch data")
  }

  return res.json()
}

export function useAccounts() {
  const { data, error, isLoading } = useSWR<Account[]>(
    "/api/v1/accounts",
    fetcher
  )

  return {
    data,
    isLoading,
    isError: !!error
  }
}

