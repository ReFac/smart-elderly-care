import {
  Body,
  Controller,
  Post,
  Req,
  UploadedFile,
  UseGuards,
  UseInterceptors,
} from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import { AiService } from './ai.service';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';

@Controller('ai')
@UseGuards(JwtAuthGuard)
export class AiController {
  constructor(private ai: AiService) {}

  @Post('ocr')
  @UseInterceptors(FileInterceptor('file'))
  async ocr(@UploadedFile() file: Express.Multer.File, @Req() req: any) {
    return this.ai.ocr(req.user.tenantId, {
      fileName: file?.originalname,
      mimeType: file?.mimetype,
    });
  }

  @Post('extract-form')
  extract(@Body() body: { text: string; formHint?: string }, @Req() req: any) {
    return this.ai.extractForm(req.user.tenantId, body.text, body.formHint);
  }
}
