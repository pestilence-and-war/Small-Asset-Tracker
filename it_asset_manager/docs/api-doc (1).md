# API Documentation

## Assets API

### List Assets
```
GET /assets/
```
Returns a list of all assets in the system.

### Add Asset
```
POST /assets/add
```
Create a new asset.

#### Request Body
```json
{
    "asset_type": "PC/Laptop",
    "asset_tag": "LAP001",
    "serial_number": "SN12345"
}
```

### Get Asset QR Code
```
GET /assets/qr/{asset_tag}
```
Returns QR code for the specified asset.

## Employees API

### List Employees
```
GET /employees/
```
Returns a list of all employees.

### Add Employee
```
POST /employees/add
```
Create a new employee record.

#### Request Body
```json
{
    "name": "John Doe",
    "email": "john@example.com",
    "department": "IT"
}
```

## Assignments API

### List Assignments
```
GET /assignments/
```
Returns all asset assignments.

### Create Assignment
```
POST /assignments/add
```
Create a new asset assignment.

#### Request Body
```json
{
    "asset_id": 1,
    "employee_id": 1
}
```

### Return Asset
```
POST /assignments/{id}/return
```
Mark an asset as returned.

## Status Codes
- 200: Success
- 400: Bad Request
- 404: Not Found
- 500: Server Error

## Error Responses
```json
{
    "error": "Error message description"
}
```

## Response Headers
- Content-Type: application/json
- X-Total-Count: Total number of records (for list endpoints)

## Rate Limiting
- 100 requests per minute per IP
- X-RateLimit-Remaining header shows remaining requests

## Authentication
*Note: Authentication to be implemented in future versions*
