export type User = {
  id: number
  name: string
  email: string
  role: string
  status: 'active' | 'invited'
}

export type UsersResponse = { users: User[] }
