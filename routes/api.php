<?php

use App\Http\Controllers\Auth\AuthController;
use App\Http\Controllers\CredentialController;
use App\Http\Controllers\StepUpController;
use App\Http\Controllers\ProcessoController;
use App\Http\Controllers\AdminController;
use Illuminate\Support\Facades\Route;
use App\Http\Controllers\AutoridadeController;
use App\Http\Controllers\NotaBGController;

/*
|--------------------------------------------------------------------------
| API Routes - PlattArgus
|--------------------------------------------------------------------------
|
| Todas as rotas são prefixadas com /api
| Autenticação via Sanctum (Bearer token) ou Session
|
*/

// =========================================================================
// ROTAS PÚBLICAS (Sem autenticação)
// =========================================================================

Route::prefix('auth')->group(function () {
    // Login
    Route::post('/login', [AuthController::class, 'login'])
        ->middleware('throttle:login')
        ->name('auth.login');

    // Primeiro acesso (legado - para usuários pré-cadastrados)
    Route::post('/primeiro-acesso', [AuthController::class, 'primeiroAcesso'])
        ->middleware('throttle:login')
        ->name('auth.primeiro-acesso');

    // Validar matrícula na API de Efetivo
    Route::post('/validar-matricula', [AuthController::class, 'validarMatricula'])
        ->middleware('throttle:login')
        ->name('auth.validar-matricula');

    // Cadastro via matrícula do efetivo
    Route::post('/cadastrar', [AuthController::class, 'cadastrar'])
        ->middleware('throttle:login')
        ->name('auth.cadastrar');
});

// Health check
Route::get('/health', function () {
    return response()->json([
        'status' => 'ok',
        'app' => 'PlattArgus',
        'version' => config('app.version', '1.0.0'),
        'timestamp' => now()->toIso8601String(),
    ]);
})->name('health');


// =========================================================================
// ROTAS AUTENTICADAS
// =========================================================================

Route::middleware(['auth:sanctum'])->group(function () {
    
    // -----------------------------------------------------------------
    // AUTENTICAÇÃO
    // -----------------------------------------------------------------
    Route::prefix('auth')->group(function () {
        Route::post('/verificar', [AuthController::class, 'verificar'])->name('auth.verificar');
        Route::post('/logout', [AuthController::class, 'logout'])->name('auth.logout');
        Route::post('/alterar-senha', [AuthController::class, 'alterarSenha'])->name('auth.alterar-senha');
        Route::get('/me', [AuthController::class, 'me'])->name('auth.me');
    });
    
    // -----------------------------------------------------------------
    // CREDENCIAIS SEI
    // -----------------------------------------------------------------
    Route::prefix('credencial')->group(function () {
        Route::get('/status', [CredentialController::class, 'status'])->name('credencial.status');
        Route::post('/vincular', [CredentialController::class, 'vincular'])->name('credencial.vincular');
        Route::delete('/', [CredentialController::class, 'remover'])->name('credencial.remover');
        Route::put('/senha', [CredentialController::class, 'atualizarSenha'])->name('credencial.atualizar-senha');
        Route::put('/cargo', [CredentialController::class, 'atualizarCargo'])->name('credencial.atualizar-cargo');
        Route::post('/testar', [CredentialController::class, 'testar'])->name('credencial.testar');
        Route::get('/orgaos', [CredentialController::class, 'orgaos'])->name('credencial.orgaos');
        Route::get('/cargos', [CredentialController::class, 'cargos'])->name('credencial.cargos');
    });
    
    // -----------------------------------------------------------------
    // STEP-UP AUTHENTICATION
    // -----------------------------------------------------------------
    Route::prefix('step-up')->group(function () {
        Route::post('/grant', [StepUpController::class, 'grant'])
            ->middleware('throttle:step-up')
            ->name('step-up.grant');
        Route::post('/verify', [StepUpController::class, 'verify'])->name('step-up.verify');
        Route::get('/active', [StepUpController::class, 'active'])->name('step-up.active');
        Route::delete('/invalidate', [StepUpController::class, 'invalidate'])->name('step-up.invalidate');
    });
    
    // -----------------------------------------------------------------
    // PROCESSOS SEI
    // -----------------------------------------------------------------
    Route::prefix('processos')->group(function () {
        // Criar processo
        Route::post('/criar', [ProcessoController::class, 'criarProcesso'])->name('processos.criar');

        // Análise
        Route::post('/analisar', [ProcessoController::class, 'analisar'])->name('processos.analisar');
        Route::get('/analises', [ProcessoController::class, 'listarAnalises'])->name('processos.analises');
        Route::get('/analises/{id}', [ProcessoController::class, 'obterAnalise'])->name('processos.analise');
        
        // Documentos
        Route::post('/gerar-documento', [ProcessoController::class, 'gerarDocumento'])->name('processos.gerar-documento');
        Route::post('/inserir-sei', [ProcessoController::class, 'inserirSei'])->name('processos.inserir-sei');
        Route::get('/documentos', [ProcessoController::class, 'listarDocumentos'])->name('processos.documentos');
        
        // Assinatura (requer step-up)
        Route::post('/assinar', [ProcessoController::class, 'assinar'])->name('processos.assinar');

        // Enviar e atribuir
        Route::post('/enviar', [ProcessoController::class, 'enviarProcesso'])->name('processos.enviar');
        Route::post('/atribuir', [ProcessoController::class, 'atribuirProcesso'])->name('processos.atribuir');

        // Chat e consultas
        Route::post('/chat', [ProcessoController::class, 'chat'])->name('processos.chat');
        Route::post('/consultar-lei', [ProcessoController::class, 'consultarLei'])->name('processos.consultar-lei');
    });

    // -----------------------------------------------------------------
    // NOTA PARA BOLETIM GERAL
    // -----------------------------------------------------------------
    Route::prefix('nota-bg')->group(function () {
        Route::post('/inserir', [NotaBGController::class, 'inserir'])->name('nota-bg.inserir');
    });

    // -----------------------------------------------------------------
    // BLOCOS DE ASSINATURA (NOVO)
    // -----------------------------------------------------------------
    Route::prefix('blocos')->group(function () {
        Route::get('/{blocoId}', [ProcessoController::class, 'listarBloco'])->name('blocos.listar');
    });
    
    Route::prefix('documento')->group(function () {
        Route::post('/visualizar', [ProcessoController::class, 'visualizarDocumento'])->name('documento.visualizar');
        Route::post('/assinar', [ProcessoController::class, 'assinarDocumentoBloco'])->name('documento.assinar');
    });
    
    Route::prefix('bloco')->group(function () {
        Route::post('/assinar', [ProcessoController::class, 'assinarBlocoCompleto'])->name('bloco.assinar');
    });
    
    // -----------------------------------------------------------------
    // ADMINISTRAÇÃO (role: admin)
    // -----------------------------------------------------------------
    Route::prefix('admin')->middleware(['role:admin'])->group(function () {
        // Usuários
        Route::get('/usuarios', [AdminController::class, 'listarUsuarios'])->name('admin.usuarios');
        Route::post('/usuarios', [AdminController::class, 'criarUsuario'])->name('admin.criar-usuario');
        Route::put('/usuarios/{id}', [AdminController::class, 'atualizarUsuario'])->name('admin.atualizar-usuario');
        Route::delete('/usuarios/{id}', [AdminController::class, 'desativarUsuario'])->name('admin.desativar-usuario');
        Route::post('/usuarios/{id}/reativar', [AdminController::class, 'reativarUsuario'])->name('admin.reativar-usuario');
        Route::post('/usuarios/{id}/reset-senha', [AdminController::class, 'resetSenha'])->name('admin.reset-senha');
        
        // Auditoria
        Route::get('/auditoria', [AdminController::class, 'auditoria'])->name('admin.auditoria');
        Route::get('/auditoria/usuario/{id}', [AdminController::class, 'auditoriaUsuario'])->name('admin.auditoria-usuario');
        
        // Estatísticas
        Route::get('/estatisticas', [AdminController::class, 'estatisticas'])->name('admin.estatisticas');
        
        // Engine
        Route::get('/engine/health', [AdminController::class, 'engineHealth'])->name('admin.engine-health');
    });
});

// =========================================================================
// ROTAS INTERNAS (Engine → Laravel)
// =========================================================================

Route::prefix('internal')->middleware(['internal.hmac'])->group(function () {
    // Callback quando job termina
    Route::post('/jobs/{jobId}/done', function ($jobId, \Illuminate\Http\Request $request) {
        // Atualiza status do job
        \App\Models\SeiJob::where('id', $jobId)->update([
            'status' => $request->status ?? 'done',
            'result_data' => $request->result,
            'error_message' => $request->error,
            'finished_at' => now(),
        ]);
        
        return response()->json(['received' => true]);
    })->name('internal.job-done');
    
    // Atualiza progresso do job
    Route::post('/jobs/{jobId}/progress', function ($jobId, \Illuminate\Http\Request $request) {
        \App\Models\SeiJob::where('id', $jobId)->update([
            'progress_pct' => $request->progress_pct ?? 0,
            'progress_step' => $request->progress_step,
        ]);
        
        return response()->json(['received' => true]);
    })->name('internal.job-progress');
});

// =========================================================================
// ROTAS ADICIONAIS PARA COMPATIBILIDADE COM FRONTEND v2.0
// =========================================================================

Route::middleware(['auth:sanctum'])->group(function () {
    // Validar documento
    Route::post('/validar', [ProcessoController::class, 'validarDocumento'])->name('validar');
    
    // Melhorar texto com IA
    Route::post('/melhorar-texto', [ProcessoController::class, 'melhorarTexto'])->name('melhorar-texto');
    
    // Upload de arquivo para chat
    Route::post('/upload-arquivo', [ProcessoController::class, 'uploadArquivo'])->name('upload-arquivo');
    
    // Autoridades e Templates
    Route::get('/autoridades', [AutoridadeController::class, 'index'])->name('autoridades.index');
    Route::get('/autoridades/{sigla}', [AutoridadeController::class, 'show'])->name('autoridades.show');
    Route::get('/tipos-documento', [AutoridadeController::class, 'tiposDocumento'])->name('tipos-documento');
    Route::get('/templates', [AutoridadeController::class, 'templates'])->name('templates.index');
    Route::get('/templates/{codigo}', [AutoridadeController::class, 'template'])->name('templates.show');
    Route::post('/templates/{codigo}/preview', [AutoridadeController::class, 'previewTemplate'])->name('templates.preview');
});
