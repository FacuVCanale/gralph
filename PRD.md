# Simple Go HTTP Server - Learning Project

A basic Go HTTP server with 4 endpoints to learn Go web development fundamentals.

## Overview

Build a simple REST API server in Go that demonstrates:
- HTTP routing
- JSON request/response handling
- Basic CRUD operations (in-memory)
- Error handling
- Middleware basics

## Data Model

A simple `Task` struct for a todo-like application:

```go
type Task struct {
    ID          string    `json:"id"`
    Title       string    `json:"title"`
    Description string    `json:"description"`
    Completed   bool      `json:"completed"`
    CreatedAt   time.Time `json:"created_at"`
}
```

## Tasks

- [x] Set up Go project with go.mod and create main.go with a basic HTTP server listening on port 8080
- [x] Create GET /tasks endpoint that returns a list of all tasks as JSON
- [x] Create POST /tasks endpoint that accepts JSON body to create a new task and returns the created task
- [ ] Create GET /tasks/{id} endpoint that returns a single task by ID or 404 if not found
- [ ] Create DELETE /tasks/{id} endpoint that deletes a task by ID and returns 204 No Content on success

## Technical Requirements

- Use only the Go standard library (net/http, encoding/json)
- Store tasks in-memory using a slice or map (no database needed)
- Return appropriate HTTP status codes (200, 201, 204, 400, 404, 500)
- Include proper Content-Type headers (application/json)
- Handle JSON encoding/decoding errors gracefully

## Example Requests

### List all tasks
```bash
curl http://localhost:8080/tasks
```

### Create a task
```bash
curl -X POST http://localhost:8080/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Learn Go", "description": "Build a REST API"}'
```

### Get a single task
```bash
curl http://localhost:8080/tasks/abc123
```

### Delete a task
```bash
curl -X DELETE http://localhost:8080/tasks/abc123
```

## Success Criteria

- Server starts without errors
- All 4 endpoints work as specified
- JSON responses are properly formatted
- Error cases return appropriate status codes
