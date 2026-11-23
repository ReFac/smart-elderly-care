import { Body, Controller, Delete, Get, Param, Patch, Post, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { InventoryService } from './inventory.service';

@Controller('inventory')
@UseGuards(JwtAuthGuard)
export class InventoryController {
  constructor(private inventory: InventoryService) {}

  @Get('items/low-stock')
  low(@Req() req: any) {
    return this.inventory.lowStock(req.user.tenantId);
  }

  @Get('items')
  items(@Req() req: any) {
    return this.inventory.listItems(req.user.tenantId);
  }

  @Post('items')
  create(@Body() body: any, @Req() req: any) {
    return this.inventory.createItem(req.user.tenantId, body);
  }

  @Patch('items/:id')
  update(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.inventory.updateItem(id, req.user.tenantId, body);
  }

  @Post('items/:id/stock')
  stock(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.inventory.stock(id, req.user.tenantId, body.type || 'in', Number(body.quantity), body.remark);
  }

  @Delete('items/:id')
  remove(@Param('id') id: string, @Req() req: any) {
    return this.inventory.deleteItem(id, req.user.tenantId);
  }

  @Get('maintenance')
  maintenance(@Req() req: any) {
    return this.inventory.listMaintenance(req.user.tenantId);
  }

  @Post('maintenance')
  createMaint(@Body() body: any, @Req() req: any) {
    return this.inventory.createMaintenance(req.user.tenantId, body);
  }

  @Patch('maintenance/:id')
  updateMaint(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.inventory.updateMaintenance(id, req.user.tenantId, body);
  }
}
