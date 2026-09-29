/** Demo user record; Discord member profiles use a separate schema. */
export type User = {
  id: number
  name: string
  email: string
  role: string
  status: 'active' | 'invited'
}

/** Collection envelope returned by GET /api/users. */
export type UsersResponse = { users: User[] }
