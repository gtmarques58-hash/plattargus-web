<?php

namespace App\Http\Controllers;

use App\Models\Autoridade;
use App\Models\TemplateDocumento;
use Illuminate\Http\Request;
use Illuminate\Http\JsonResponse;

class AutoridadeController extends Controller
{
    /**
     * Lista todas as autoridades ativas
     * GET /api/autoridades
     */
    public function index(Request $request): JsonResponse
    {
        $query = Autoridade::ativas();
        
        // Filtro por busca
        if ($request->has('busca') && $request->busca) {
            $query->buscar($request->busca);
        }
        
        // Filtro por sigla_pai (hierarquia)
        if ($request->has('pai')) {
            $query->where('sigla_pai', $request->pai);
        }
        
        $autoridades = $query->get();
        
        return response()->json([
            'sucesso' => true,
            'autoridades' => $autoridades->map(function ($a) {
                return [
                    'id' => $a->id,
                    'sigla' => $a->sigla,
                    'nome' => $a->nome,
                    'posto_grad' => $a->posto_grad,
                    'cargo' => $a->cargo,
                    'unidade' => $a->unidade,
                    'sigla_sei' => $a->sigla_sei,
                    'portaria' => $a->portaria,
                    'nome_completo' => $a->nome_completo,
                    'opcao_dropdown' => $a->opcao_dropdown,
                ];
            }),
            'total' => $autoridades->count(),
        ]);
    }
    
    /**
     * Busca autoridade por sigla
     * GET /api/autoridades/{sigla}
     */
    public function show(string $sigla): JsonResponse
    {
        $autoridade = Autoridade::where('sigla', strtoupper($sigla))->first();
        
        if (!$autoridade) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Autoridade não encontrada',
            ], 404);
        }
        
        return response()->json([
            'sucesso' => true,
            'autoridade' => $autoridade,
        ]);
    }
    
    /**
     * Lista tipos de documento (para dropdown)
     * GET /api/tipos-documento
     */
    public function tiposDocumento(): JsonResponse
    {
        $tipos = TemplateDocumento::ativos()
            ->select('tipo_sei')
            ->distinct()
            ->orderBy('tipo_sei')
            ->pluck('tipo_sei');
        
        return response()->json([
            'sucesso' => true,
            'tipos' => $tipos,
        ]);
    }
    
    /**
     * Lista templates de documento
     * GET /api/templates
     */
    public function templates(Request $request): JsonResponse
    {
        $query = TemplateDocumento::ativos();
        
        // Filtro por tipo
        if ($request->has('tipo') && $request->tipo) {
            $query->porTipo($request->tipo);
        }
        
        // Filtro por categoria
        if ($request->has('categoria') && $request->categoria) {
            $query->porCategoria($request->categoria);
        }
        
        $templates = $query->get();
        
        return response()->json([
            'sucesso' => true,
            'templates' => $templates->map(function ($t) {
                return [
                    'id' => $t->id,
                    'codigo' => $t->codigo,
                    'tipo_sei' => $t->tipo_sei,
                    'categoria' => $t->categoria,
                    'nome' => $t->nome,
                    'descricao' => $t->descricao,
                    'campos' => $t->campos,
                    'remetente_tipo' => $t->remetente_tipo,
                ];
            }),
            'total' => $templates->count(),
        ]);
    }
    
    /**
     * Obtém template específico
     * GET /api/templates/{codigo}
     */
    public function template(string $codigo): JsonResponse
    {
        $template = TemplateDocumento::where('codigo', $codigo)->first();
        
        if (!$template) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Template não encontrado',
            ], 404);
        }
        
        return response()->json([
            'sucesso' => true,
            'template' => $template,
        ]);
    }
    
    /**
     * Preview de documento (preenche template sem salvar)
     * POST /api/templates/{codigo}/preview
     */
    public function previewTemplate(Request $request, string $codigo): JsonResponse
    {
        $template = TemplateDocumento::where('codigo', $codigo)->first();
        
        if (!$template) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Template não encontrado',
            ], 404);
        }
        
        $dados = $request->all();
        $faltantes = $template->validarCampos($dados);
        
        $html = $template->preencher($dados);
        
        return response()->json([
            'sucesso' => true,
            'html' => $html,
            'campos_faltantes' => $faltantes,
            'completo' => empty($faltantes),
        ]);
    }
}
