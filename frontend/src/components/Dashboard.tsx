import React, { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Video, Search, Plus, Play, CheckCircle2, AlertCircle, Loader2, X, Download, Upload, Trash2, Layers, MoreVertical, RotateCcw } from 'lucide-react';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const INTERNAL_API_KEY = 'hNRAKvDFPcpeJICTfpgPqcHFodRW5Kbd4vjTHRPlMTg';

const Dashboard = () => {
    // ... rest of the component

    const [profile, setProfile] = useState('');
    const [videoCount, setVideoCount] = useState(10);
    const [loading, setLoading] = useState(false);
    const [videos, setVideos] = useState<any[]>([]);
    const [overlays, setOverlays] = useState<any[]>([]);
    const [uploadingOverlay, setUploadingOverlay] = useState(false);
    const [selectedVideo, setSelectedVideo] = useState<any>(null);
    const [baseDescription, setBaseDescription] = useState(() => localStorage.getItem('baseDescription') || '');
    const [statusFilter, setStatusFilter] = useState<'all' | 'ready' | 'processing' | 'failed'>('all');

    // Destinations & Global Queue state
    const [destinations, setDestinations] = useState<any[]>([]);
    const [editingDest, setEditingDest] = useState<any>({ name: 'Автопубликация', is_active: false, posts_per_day: 3, platforms: [], publish_mode: 'auto', publish_window_start: '09:00', publish_window_end: '22:00', min_time_between_posts_minutes: 60 });
    const [globalQueue, setGlobalQueue] = useState<any>(null);
    const [destSaving, setDestSaving] = useState(false);
    const [currentProfileId, setCurrentProfileId] = useState<number | null>(null);
    const [activityLogs, setActivityLogs] = useState<any[]>([]);
    const [publishingVideoId, setPublishingVideoId] = useState<number | null>(null);
    const [envStatus, setEnvStatus] = useState<{ env_key_configured: boolean; env_profile_configured: boolean; env_key_preview: string | null } | null>(null);
    const [uploadPostProfiles, setUploadPostProfiles] = useState<any[]>([]);

    // Upload own video modal state
    const [uploadModal, setUploadModal] = useState(false);
    const [uploadFiles, setUploadFiles] = useState<File[]>([]);
    const [uploadMode, setUploadMode] = useState<'raw' | 'overlay' | 'full'>('raw');
    const [uploadProgress, setUploadProgress] = useState<number>(0);
    const [uploadUploading, setUploadUploading] = useState(false);
    const [bulkDescriptionUpdating, setBulkDescriptionUpdating] = useState(false);


    // Subtitle settings state with localStorage persistence
    // Preset visual definitions for frontend
    const SUBTITLE_PRESETS = [
        { id: 'classic', label: 'Классический', desc: '5 слов, белый текст', emoji: '📝', fontSize: 14, color: '#FFFFFF', outline: '#000000', bg: false },
        { id: 'word', label: 'По 1 слову', desc: 'Крупно, по центру', emoji: '🔤', fontSize: 18, color: '#FFFFFF', outline: '#000000', bg: false },
        { id: 'karaoke', label: 'Караоке', desc: '2 слова, жёлтый', emoji: '🎤', fontSize: 16, color: '#FFD700', outline: '#000000', bg: false },
        { id: 'mrbeast', label: 'MrBeast', desc: 'Огромный, жёлтый/красный', emoji: '🔥', fontSize: 20, color: '#FFD700', outline: '#FF0000', bg: false },
        { id: 'hormozi', label: 'Hormozi', desc: 'Белый на фоне', emoji: '🖤', fontSize: 16, color: '#FFFFFF', outline: '#000000', bg: true },
    ];

    const [subtitles, setSubtitles] = useState(() => {
        try {
            const saved = localStorage.getItem('subtitle_settings');
            const parsed = saved ? JSON.parse(saved) : {};
            return {
                enabled: parsed.enabled ?? true,
                preset: parsed.preset || 'classic',
                use_custom_styles: parsed.use_custom_styles || false,
                has_outline: parsed.has_outline ?? true,
                font_size: parsed.font_size || 28,
                primary_color: parsed.primary_color || '#FFFFFF',
                outline_color: parsed.outline_color || '#000000',
                vertical_position: parsed.vertical_position || 120,
            };
        } catch (e) {
            return {
                enabled: true,
                preset: 'classic',
                use_custom_styles: false,
                has_outline: true,
                font_size: 28,
                primary_color: '#FFFFFF',
                outline_color: '#000000',
                vertical_position: 120,
            };
        }
    });

    // Overlay design state with localStorage persistence
    const [overlayDesign, setOverlayDesign] = useState(() => {
        try {
            const saved = localStorage.getItem('overlay_design_settings');
            return saved ? JSON.parse(saved) : {
                selected_id: null as number | null,
                y_position: 0,
                scale: 100,
            };
        } catch (e) {
            return { selected_id: null, y_position: 0, scale: 100 };
        }
    });

    // Save subtitles and overlay design to localStorage when they change
    React.useEffect(() => {
        localStorage.setItem('subtitle_settings', JSON.stringify(subtitles));
    }, [subtitles]);
    React.useEffect(() => {
        localStorage.setItem('overlay_design_settings', JSON.stringify(overlayDesign));
    }, [overlayDesign]);

    // Use stable refs for polling functions to avoid stale closures in setInterval
    const pollingInterval = React.useRef<any | null>(null);

    const startPolling = React.useCallback(() => {
        if (pollingInterval.current) clearInterval(pollingInterval.current);

        fetchVideos();
        fetchOverlays();
        fetchActivity();
        fetchDestinations();
        fetchUploadPostProfiles();
        fetchGlobalQueue();

        pollingInterval.current = setInterval(() => {
            fetchVideos();
            fetchActivity();
            fetchGlobalQueue();
        }, 5000);
    }, [currentProfileId]); // Restart if profile changes to update activity endpoint

    React.useEffect(() => {
        startPolling();

        // Load ENV status for autopublish indicator
        fetch(`${API}/api/autopublish/status`)
            .then(r => r.ok ? r.json() : null)
            .then(d => d && setEnvStatus(d))
            .catch(() => { });

        return () => {
            if (pollingInterval.current) clearInterval(pollingInterval.current);
        };
    }, [startPolling]);

    const fetchActivity = async () => {
        try {
            const endpoint = currentProfileId
                ? `${API}/api/activity/${currentProfileId}`
                : `${API}/api/activity`;
            const response = await fetch(endpoint);
            if (response.ok) {
                const data = await response.json();
                setActivityLogs(data);
            }
        } catch (err) {
            console.error("Failed to fetch activity:", err);
        }
    };

    const fetchVideos = async () => {
        try {
            const response = await fetch(`${API}/api/videos`, {
                headers: { 'X-Internal-API-Key': INTERNAL_API_KEY }
            });
            if (response.ok) {
                const data = await response.json();
                setVideos(data);
            }
        } catch (err) {
            console.error("Failed to fetch videos:", err);
        }
    };

    const fetchOverlays = async () => {
        try {
            const response = await fetch(`${API}/api/overlays`, {
                headers: { 'X-Internal-API-Key': INTERNAL_API_KEY }
            });
            if (response.ok) {
                const data = await response.json();
                setOverlays(data);
            }
        } catch (err) {
            console.error("Failed to fetch overlays:", err);
        }
    };

    const deleteAllVideos = async () => {
        if (!window.confirm("Вы уверены, что хотите удалить ВСЕ ролики из базы данных? Это действие необратимо.")) {
            return;
        }

        setLoading(true);
        try {
            const response = await fetch(`${API}/api/videos/all`, {
                method: 'DELETE',
                headers: { 'X-Internal-API-Key': INTERNAL_API_KEY }
            });
            if (response.ok) {
                setVideos([]);
                fetchActivity();
            } else {
                const error = await response.json();
                alert("Ошибка удаления: " + error.detail);
            }
        } catch (err) {
            console.error("Failed to delete videos:", err);
            alert("Ошибка сети при удалении");
        } finally {
            setLoading(false);
        }
    };

    const handleFetch = async () => {
        if (!profile) return;
        setLoading(true);
        try {
            const subtitle_style_payload: any = {
                preset: subtitles.preset || 'classic',
            };
            if (subtitles.use_custom_styles) {
                subtitle_style_payload.font_size = subtitles.font_size;
                subtitle_style_payload.primary_color = subtitles.primary_color;
                subtitle_style_payload.has_outline = subtitles.has_outline;
                subtitle_style_payload.outline_color = subtitles.outline_color;
                subtitle_style_payload.vertical_position = subtitles.vertical_position;
            }

            const response = await fetch(`${API}/api/campaigns`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Internal-API-Key': INTERNAL_API_KEY
                },
                body: JSON.stringify({
                    username: profile,
                    video_count: videoCount,
                    base_description: baseDescription,
                    enable_subtitles: subtitles.enabled,
                    subtitle_style: subtitle_style_payload,
                    overlay_settings: {
                        y_position: overlayDesign.y_position,
                        scale: overlayDesign.scale,
                    }
                })
            });
            if (response.ok) {
                const data = await response.json();
                if (data.profile_id) {
                    setCurrentProfileId(data.profile_id);
                }
            }
        } catch (err) {
            console.error("Failed to start campaign:", err);
            alert("Ошибка запуска кампании: " + err);
        } finally {
            setLoading(false);
            fetchVideos();
            // Automatically switch to "All Videos" tab to show progress
            const tabsList = document.querySelector('[role="tablist"]');
            const allVideosTab = tabsList?.querySelector('[value="all"]') as HTMLElement;
            allVideosTab?.click();
        }
    };

    const handleUpload = () => {
        if (uploadFiles.length === 0) return;
        setUploadUploading(true);
        setUploadProgress(0);
        const form = new FormData();
        uploadFiles.forEach(f => form.append('files', f));
        form.append('profile', profile || 'default');
        form.append('mode', uploadMode);
        const xhr = new XMLHttpRequest();
        xhr.open('POST', `${API}/api/videos/upload`);
        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) setUploadProgress(Math.round((e.loaded / e.total) * 100));
        };
        xhr.onload = () => {
            setUploadUploading(false);
            setUploadProgress(0);
            setUploadModal(false);
            setUploadFiles([]);
            fetchVideos();
        };
        xhr.onerror = () => {
            setUploadUploading(false);
            console.error('Upload failed');
        };
        xhr.send(form);
    };

    const DEFAULT_AUTOPUB = { name: 'Автопубликация', is_active: false, posts_per_day: 3, platforms: [] as string[], uploadpost_profiles: [] as string[], publish_mode: 'auto', publish_window_start: '09:00', publish_window_end: '22:00', min_time_between_posts_minutes: 60 };

    const fetchDestinations = async () => {
        try {
            const res = await fetch(`${API}/api/destinations`, {
                headers: { 'X-Internal-API-Key': INTERNAL_API_KEY }
            });
            if (res.ok) {
                const data = await res.json();
                setDestinations(data);
                // Single-config model: load first destination or defaults
                if (data.length > 0) {
                    setEditingDest(data[0]);
                } else if (!editingDest?.id) {
                    setEditingDest({ ...DEFAULT_AUTOPUB });
                }
            }
        } catch (err) { console.error(err); }
    };

    const fetchUploadPostProfiles = async () => {
        try {
            const res = await fetch(`${API}/api/autopublish/profiles`, {
                headers: { 'X-Internal-API-Key': INTERNAL_API_KEY }
            });
            if (res.ok) {
                const data = await res.json();
                if (data.success && data.profiles) setUploadPostProfiles(data.profiles);
            }
        } catch (err) { console.error('fetchUploadPostProfiles error:', err); }
    };

    const fetchGlobalQueue = async () => {
        try {
            const res = await fetch(`${API}/api/videos/global-queue`, {
                headers: { 'X-Internal-API-Key': INTERNAL_API_KEY }
            });
            if (res.ok) setGlobalQueue(await res.json());
        } catch { }
    };

    const saveDestination = async (dest: any) => {
        setDestSaving(true);
        try {
            const method = dest.id ? 'PUT' : 'POST';
            const url = dest.id ? `${API}/api/destinations/${dest.id}` : `${API}/api/destinations`;
            const res = await fetch(url, {
                method,
                headers: {
                    'Content-Type': 'application/json',
                    'X-Internal-API-Key': INTERNAL_API_KEY
                },
                body: JSON.stringify(dest)
            });
            if (res.ok) {
                const saved = await res.json();
                setEditingDest(saved);
                fetchDestinations();
            }
        } catch (err) { console.error('Failed to save:', err); }
        finally { setDestSaving(false); }
    };


    const publishNow = async (videoId: number, destId: number) => {
        setPublishingVideoId(videoId);
        try {
            const res = await fetch(`${API}/api/destinations/${destId}/publish-now/${videoId}`, {
                method: 'POST',
                headers: { 'X-Internal-API-Key': INTERNAL_API_KEY }
            });
            const data = await res.json();
            if (data.success) {
                fetchVideos();
                fetchGlobalQueue();
            } else {
                alert('Ошибка публикации: ' + (data.error || data.message));
            }
        } catch (err) { alert('Ошибка соединения'); }
        finally { setPublishingVideoId(null); }
    };

    const [statusMenuVideoId, setStatusMenuVideoId] = useState<number | null>(null);

    const changeVideoStatus = async (videoId: number, updates: { status?: string; publish_status?: string | null }) => {
        try {
            const res = await fetch(`${API}/api/videos/${videoId}/status`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Internal-API-Key': INTERNAL_API_KEY
                },
                body: JSON.stringify(updates),
            });
            if (res.ok) {
                fetchVideos();
                fetchGlobalQueue();
            } else {
                const err = await res.json();
                alert('Ошибка: ' + (err.detail || 'Неизвестная ошибка'));
            }
        } catch { alert('Ошибка соединения'); }
        finally { setStatusMenuVideoId(null); }
    };


    const handleBulkUpdateDescription = async () => {
        if (!baseDescription) {
            alert("Сначала введите описание в поле выше.");
            return;
        }
        if (!window.confirm("Вы уверены, что хотите заменить описание у ВСЕХ готовых, но еще неопубликованных видео?")) {
            return;
        }

        setBulkDescriptionUpdating(true);
        try {
            const res = await fetch(`${API}/api/videos/bulk-update-description`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Internal-API-Key': INTERNAL_API_KEY
                },
                body: JSON.stringify({ description: baseDescription }),
            });
            if (res.ok) {
                const data = await res.json();
                alert(data.message);
                fetchVideos();
            } else {
                const err = await res.json();
                alert('Ошибка: ' + (err.detail || 'Неизвестная ошибка'));
            }
        } catch { alert('Ошибка соединения'); }
        finally { setBulkDescriptionUpdating(false); }
    };


    const handleOverlayUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {

        const file = e.target.files?.[0];
        if (!file) return;

        setUploadingOverlay(true);
        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch(`${API}/api/overlays/upload`, {
                method: 'POST',
                headers: { 'X-Internal-API-Key': INTERNAL_API_KEY },
                body: formData,
            });
            if (response.ok) {
                fetchOverlays();
            }
        } catch (err) {
            console.error("Failed to upload overlay:", err);
        } finally {
            setUploadingOverlay(false);
        }
    };

    const deleteOverlay = async (id: number) => {
        try {
            await fetch(`${API}/api/overlays/${id}`, {
                method: 'DELETE',
                headers: { 'X-Internal-API-Key': INTERNAL_API_KEY }
            });
            fetchOverlays();
        } catch (err) {
            console.error("Failed to delete overlay:", err);
        }
    };


    const getStatusBadge = (status: string) => {
        if (status === 'merged') {
            return (
                <Badge className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20">
                    <CheckCircle2 className="mr-1 h-3 w-3" /> Готово
                </Badge>
            );
        }
        if (status.includes('failed')) {
            return (
                <Badge className="bg-rose-500/10 text-rose-500 border-rose-500/20">
                    <AlertCircle className="mr-1 h-3 w-3" /> Ошибка
                </Badge>
            );
        }
        if (status === 'skipped (no product)') {
            return (
                <Badge className="bg-slate-500/10 text-slate-500 border-slate-500/20">
                    <AlertCircle className="mr-1 h-3 w-3" /> Нет товара
                </Badge>
            );
        }
        if (status === 'queued') {
            return (
                <Badge className="bg-amber-500/10 text-amber-500 border-amber-500/20 animate-pulse">
                    <Loader2 className="mr-1 h-3 w-3" /> В очереди
                </Badge>
            );
        }
        return (
            <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20 animate-pulse">
                <Loader2 className="mr-1 h-3 w-3 animate-spin" /> {status}
            </Badge>
        );
    };

    // Get video stream URL:
    // 1. If local file exists — serve via /outputs
    // 2. If GCS video — redirect via signed URL through /api/videos/{id}/stream
    const getVideoUrl = (video: any): string | null => {
        // Local file still exists (no GCS or local fallback mode)
        if (video.local_video_path) {
            const cleanPath = video.local_video_path.replace(/^\/+/, '');
            // Check it's not a GCS path
            if (!cleanPath.startsWith('gs://') && !cleanPath.startsWith('local://')) {
                return `${API}/${cleanPath}`;
            }
        }
        // GCS: use stream endpoint that returns a signed URL
        if (video.processed_video_path?.startsWith('gs://') || video.gcs_path?.startsWith('gs://')) {
            return `${API}/api/videos/${video.id}/stream`;
        }
        return null;
    };

    // Get specific download URL (forces attachment header)
    const getDownloadUrl = (video: any): string | null => {
        const url = getVideoUrl(video);
        if (url && url.includes('/stream')) {
            return `${url}?download=1`;
        }
        return url;
    };

    // Get thumbnail URL: prefer GCS-cached cover if available, then direct TikTok link
    const getThumbnailUrl = (video: any): string | null => {
        if (video.thumbnail_url?.startsWith('gs://')) {
            return `${API}/api/storage/url?gs_uri=${encodeURIComponent(video.thumbnail_url)}`;
        }
        return video.thumbnail_url || null;
    };

    return (
        <div className="min-h-screen bg-slate-950 text-slate-50 p-6 md:p-12 font-sans">
            <div className="max-w-7xl mx-auto space-y-8">
                {/* Header */}
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div>
                        <h1 className="text-4xl font-bold tracking-tight bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent">
                            TikTok Content Manager
                        </h1>
                        <p className="text-slate-400 mt-2">Анализ, генерация озвучки и наложение плашек на видео.</p>
                    </div>
                    <div className="text-sm text-slate-500">
                        <span className="font-semibold text-slate-300">{videos.filter(v => v.status === 'merged').length}</span> из <span className="font-semibold text-slate-300">{videos.length}</span> видео готово
                    </div>
                </div>

                {/* Input Section */}
                <Card className="bg-slate-900/50 border-slate-800 backdrop-blur-xl shadow-2xl">
                    <CardHeader>
                        <CardTitle>Загрузить новый контент</CardTitle>
                        <CardDescription className="text-slate-400">
                            Введите юзернейм TikTok профиля чтобы начать автоматическую обработку.
                        </CardDescription>
                    </CardHeader>
                    <CardContent>
                        <div className="space-y-4">
                            <div className="flex flex-col md:flex-row gap-4">
                                <div className="flex-1 relative">
                                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                                    <Input
                                        placeholder="@username"
                                        value={profile}
                                        onChange={(e) => setProfile(e.target.value)}
                                        onKeyDown={(e) => e.key === 'Enter' && handleFetch()}
                                        className="pl-10 bg-slate-950/50 border-slate-800 focus-visible:ring-blue-500 text-slate-50 placeholder:text-slate-500"
                                    />
                                </div>
                                <div className="w-full md:w-32">
                                    <Input
                                        type="number"
                                        min="1"
                                        max="100"
                                        value={videoCount}
                                        onChange={(e) => setVideoCount(Number(e.target.value))}
                                        className="bg-slate-950/50 border-slate-800 focus-visible:ring-blue-500 text-slate-50"
                                    />
                                </div>
                                <Button
                                    variant="outline"
                                    onClick={() => setUploadModal(true)}
                                    className="border-slate-700 hover:bg-slate-800 text-slate-300"
                                >
                                    <Upload className="mr-2 h-4 w-4" />
                                    Загрузить видео
                                </Button>
                                <Button
                                    onClick={handleFetch}
                                    disabled={loading || !profile}
                                    className="bg-emerald-600 hover:bg-emerald-500 transition-all duration-300"
                                >
                                    {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Video className="mr-2 h-4 w-4" />}
                                    Запустить
                                </Button>
                            </div>
                            <div className="flex flex-col gap-2">
                                <label className="text-xs font-medium text-slate-400 uppercase tracking-wider">Базовое описание для всех видео (AI адаптирует его под каждый ролик)</label>
                                <textarea
                                    className="w-full bg-slate-950/50 border border-slate-800 rounded-lg p-3 text-sm text-slate-300 min-h-[80px] focus:outline-none focus:ring-1 focus:ring-blue-500 transition-all placeholder:text-slate-600"
                                    placeholder="Введите текст поста, например: '🔥 Вау! Смотри какая находка. Ссылка в профиле!'..."
                                    value={baseDescription}
                                    onChange={(e) => { setBaseDescription(e.target.value); localStorage.setItem('baseDescription', e.target.value); }}
                                />
                            </div>
                        </div>
                    </CardContent>
                </Card>

                {/* Live Activity Feed */}
                {activityLogs.length > 0 && (
                    <Card className="bg-slate-900/50 border-slate-800 overflow-hidden shadow-xl animate-in fade-in zoom-in-95 duration-500">
                        <CardHeader className="py-2 px-4 bg-slate-950/50 flex flex-row items-center justify-between border-b border-slate-800">
                            <CardTitle className="text-[12px] font-semibold flex items-center gap-2 text-slate-300 uppercase tracking-wider">
                                <span className="relative flex h-2 w-2">
                                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                                    <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                                </span>
                                Лог активности (Live)
                            </CardTitle>
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setActivityLogs([])}
                                className="h-5 px-2 text-[10px] text-slate-500 hover:text-slate-300 hover:bg-slate-800"
                            >
                                Очистить
                            </Button>
                        </CardHeader>
                        <CardContent className="p-0">
                            <div className="max-h-[160px] overflow-y-auto p-3 space-y-1.5 font-mono text-[11px] bg-black/20">
                                {activityLogs.map((log) => (
                                    <div key={log.id} className="flex gap-3 items-start border-b border-slate-800/30 pb-1 last:border-0 animate-in slide-in-from-left-2 duration-300">
                                        <span className="text-slate-600 shrink-0 select-none">
                                            {new Date(log.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                        </span>
                                        <span className={`
                                            ${log.event_type === 'error' ? 'text-rose-400 font-semibold' : ''}
                                            ${log.event_type === 'success' ? 'text-emerald-400' : ''}
                                            ${log.event_type === 'skip' ? 'text-slate-500 italic' : ''}
                                            ${log.event_type === 'info' ? 'text-blue-400' : 'text-slate-300'}
                                        `}>
                                            {log.message}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </CardContent>
                    </Card>
                )}

                {/* Main Content Areas */}
                <Tabs defaultValue="all" className="space-y-4">
                    <TabsList className="bg-slate-900 border-slate-800 p-1">
                        <TabsTrigger value="all" className="data-[state=active]:bg-slate-800">
                            Все видео ({videos.length})
                        </TabsTrigger>
                        <TabsTrigger value="destinations" className="data-[state=active]:bg-slate-800">
                            <span className="flex items-center gap-1.5">
                                Автопубликации
                                {envStatus && (
                                    <span className={`inline-block w-2 h-2 rounded-full ${envStatus.env_key_configured ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                                )}
                            </span>
                        </TabsTrigger>
                        <TabsTrigger value="design" className="data-[state=active]:bg-slate-800">
                            <Layers className="mr-2 h-4 w-4" /> Оформление
                        </TabsTrigger>
                    </TabsList>


                    <TabsContent value="all" className="space-y-4">
                        <div className="flex flex-col md:flex-row justify-between items-center px-2 gap-4">
                            <div className="flex gap-2">
                                <Button
                                    variant={statusFilter === 'all' ? 'default' : 'outline'}
                                    size="sm"
                                    onClick={() => setStatusFilter('all')}
                                    className="text-xs"
                                >
                                    Все
                                </Button>
                                <Button
                                    variant={statusFilter === 'ready' ? 'default' : 'outline'}
                                    size="sm"
                                    onClick={() => setStatusFilter('ready')}
                                    className="text-xs border-emerald-500/50 text-emerald-400 hover:bg-emerald-500/10"
                                >
                                    Готово
                                </Button>
                                <Button
                                    variant={statusFilter === 'processing' ? 'default' : 'outline'}
                                    size="sm"
                                    onClick={() => setStatusFilter('processing')}
                                    className="text-xs border-blue-500/50 text-blue-400 hover:bg-blue-500/10"
                                >
                                    В процессе
                                </Button>
                                <Button
                                    variant={statusFilter === 'failed' ? 'default' : 'outline'}
                                    size="sm"
                                    onClick={() => setStatusFilter('failed')}
                                    className="text-xs border-rose-500/50 text-rose-400 hover:bg-rose-500/10"
                                >
                                    Ошибка
                                </Button>
                            </div>
                            <div className="flex gap-2">
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={fetchVideos}
                                    className="text-slate-500 hover:text-slate-300 text-xs"
                                >
                                    <Loader2 className={`mr-1 h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
                                    Обновить статус
                                </Button>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={deleteAllVideos}
                                    className="text-rose-500/70 hover:text-rose-400 hover:bg-rose-500/10 text-xs"
                                >
                                    <Trash2 className="mr-1 h-3 w-3" />
                                    Удалить все
                                </Button>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={handleBulkUpdateDescription}
                                    disabled={bulkDescriptionUpdating}
                                    className="border-blue-500/50 text-blue-400 hover:bg-blue-500/10 text-xs"
                                >
                                    {bulkDescriptionUpdating ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Layers className="mr-1 h-3 w-3" />}
                                    Применить описание ко всем готовым
                                </Button>
                            </div>
                        </div>

                        <Card className="bg-slate-900/30 border-slate-800 overflow-hidden">
                            <Table>
                                <TableHeader className="bg-slate-950/50">
                                    <TableRow className="border-slate-800 hover:bg-transparent">
                                        <TableHead className="w-12">#</TableHead>
                                        <TableHead className="w-20">Превью</TableHead>
                                        <TableHead>TikTok ID</TableHead>
                                        <TableHead>Длина</TableHead>
                                        <TableHead>Товар?</TableHead>
                                        <TableHead>Описание</TableHead>
                                        <TableHead>Статус</TableHead>
                                        <TableHead className="text-right">Действия</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {videos.length === 0 && (
                                        <TableRow>
                                            <TableCell colSpan={8} className="text-center py-12 text-slate-500">
                                                Видео не найдены. Введите профиль чтобы начать.
                                            </TableCell>
                                        </TableRow>
                                    )}
                                    {videos
                                        .filter(video => {
                                            if (statusFilter === 'ready') return video.status === 'merged';
                                            if (statusFilter === 'failed') return video.status?.includes('failed') || video.status === 'skipped (no product)';
                                            if (statusFilter === 'processing') return video.status && video.status !== 'merged' && !video.status.includes('failed') && video.status !== 'skipped (no product)';
                                            return true;
                                        })
                                        .map((video, index) => {
                                            const videoUrl = getVideoUrl(video);
                                            const thumbUrl = getThumbnailUrl(video);
                                            return (
                                                <TableRow key={video.id} className="border-slate-800 hover:bg-slate-800/20 transition-colors">
                                                    <TableCell className="text-slate-500 font-mono text-xs">
                                                        {index + 1}
                                                    </TableCell>
                                                    <TableCell>
                                                        <div
                                                            className={`w-14 h-20 bg-slate-800 rounded-md overflow-hidden flex items-center justify-center relative ${(thumbUrl || videoUrl) ? 'cursor-pointer group' : ''}`}
                                                            onClick={() => (thumbUrl || videoUrl) && setSelectedVideo(video)}
                                                        >
                                                            {thumbUrl ? (
                                                                <>
                                                                    <img
                                                                        src={thumbUrl}
                                                                        alt="preview"
                                                                        className="w-full h-full object-cover"
                                                                        onError={(e) => {
                                                                            (e.target as HTMLImageElement).style.display = 'none';
                                                                            const videoSibling = (e.target as HTMLImageElement).nextElementSibling as HTMLElement;
                                                                            if (videoSibling) videoSibling.style.display = 'block';
                                                                        }}
                                                                    />
                                                                    <div className="hidden absolute inset-0">
                                                                        {videoUrl && (
                                                                            <video
                                                                                src={videoUrl}
                                                                                className="w-full h-full object-cover"
                                                                                muted
                                                                                preload="metadata"
                                                                            />
                                                                        )}
                                                                    </div>
                                                                    <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                                                                        <Play className="h-5 w-5 text-white" />
                                                                    </div>
                                                                </>
                                                            ) : videoUrl ? (
                                                                <>
                                                                    <video
                                                                        src={videoUrl}
                                                                        className="w-full h-full object-cover"
                                                                        muted
                                                                        preload="metadata"
                                                                    />
                                                                    <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                                                                        <Play className="h-5 w-5 text-white" />
                                                                    </div>
                                                                </>
                                                            ) : (
                                                                <Play className="h-5 w-5 text-slate-600" />
                                                            )}
                                                        </div>
                                                    </TableCell>
                                                    <TableCell className="font-medium">
                                                        <span className="truncate max-w-[160px] block text-sm text-slate-300">{video.tiktok_id}</span>
                                                    </TableCell>
                                                    <TableCell className="text-slate-400">
                                                        {video.duration ? `${video.duration.toFixed(1)}с` : '—'}
                                                    </TableCell>
                                                    <TableCell>
                                                        {video.is_product === true && <span className="text-emerald-400 text-sm">✓ Да</span>}
                                                        {video.is_product === false && <span className="text-slate-500 text-sm">✗ Нет</span>}
                                                        {video.is_product === null && <span className="text-slate-600 text-sm">—</span>}
                                                    </TableCell>
                                                    <TableCell>
                                                        <p className="text-xs text-slate-400 leading-relaxed break-words">
                                                            {video.description || (video.status === 'merged' ? '—' : 'Генерация...')}
                                                        </p>
                                                    </TableCell>
                                                    <TableCell>
                                                        {video.publish_status === 'published' ? (
                                                            <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20 text-xs">
                                                                <CheckCircle2 className="h-3 w-3 mr-1" /> Опубликовано
                                                            </Badge>
                                                        ) : video.publish_status === 'failed' ? (
                                                            <Badge className="bg-rose-500/10 text-rose-400 border-rose-500/20 text-xs">
                                                                <AlertCircle className="h-3 w-3 mr-1" /> Ошибка публ.
                                                            </Badge>
                                                        ) : (
                                                            getStatusBadge(video.status)
                                                        )}
                                                    </TableCell>
                                                    <TableCell className="text-right">
                                                        <div className="flex gap-2 justify-end flex-wrap items-center">
                                                            {video.status === 'merged' && video.publish_status !== 'published' && destinations.length > 0 && (
                                                                <div className="flex items-center gap-1">
                                                                    <select id={`publish-dest-${video.id}`} className="text-xs bg-slate-900 border border-slate-800 rounded py-1 px-2 text-slate-300 focus:outline-none">
                                                                        {destinations.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                                                                    </select>
                                                                    <Button
                                                                        variant="outline"
                                                                        size="sm"
                                                                        className="border-emerald-700 text-emerald-400 hover:bg-emerald-900/30 hover:text-emerald-300 text-xs px-2"
                                                                        onClick={() => {
                                                                            const sel = document.getElementById(`publish-dest-${video.id}`) as HTMLSelectElement;
                                                                            if (sel) publishNow(video.id, parseInt(sel.value));
                                                                        }}
                                                                        disabled={publishingVideoId === video.id}
                                                                    >
                                                                        {publishingVideoId === video.id ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : null}
                                                                        Пуск
                                                                    </Button>
                                                                </div>
                                                            )}
                                                            {videoUrl && (
                                                                <Button
                                                                    variant="ghost"
                                                                    size="sm"
                                                                    className="text-blue-400 hover:text-blue-300 hover:bg-slate-800"
                                                                    onClick={() => setSelectedVideo(video)}
                                                                >
                                                                    <Play className="h-4 w-4 mr-1" /> Смотреть
                                                                </Button>
                                                            )}
                                                            {videoUrl && (
                                                                <a href={getDownloadUrl(video) || '#'} download>
                                                                    <Button variant="ghost" size="sm" className="text-slate-400 hover:text-slate-300 hover:bg-slate-800">
                                                                        <Download className="h-4 w-4" />
                                                                    </Button>
                                                                </a>
                                                            )}
                                                            {/* Status change dropdown */}
                                                            <div className="relative">
                                                                <Button
                                                                    variant="ghost"
                                                                    size="sm"
                                                                    className="text-slate-500 hover:text-slate-300 hover:bg-slate-800 px-1.5"
                                                                    onClick={(e) => { e.stopPropagation(); setStatusMenuVideoId(statusMenuVideoId === video.id ? null : video.id); }}
                                                                >
                                                                    <MoreVertical className="h-4 w-4" />
                                                                </Button>
                                                                {statusMenuVideoId === video.id && (
                                                                    <div className="absolute right-0 top-full mt-1 z-50 bg-slate-900 border border-slate-700 rounded-lg shadow-xl py-1 min-w-[180px] animate-in fade-in zoom-in-95 duration-150">
                                                                        {video.publish_status === 'published' && (
                                                                            <button
                                                                                className="w-full text-left px-3 py-2 text-xs text-amber-400 hover:bg-slate-800 flex items-center gap-2"
                                                                                onClick={() => changeVideoStatus(video.id, { publish_status: null })}
                                                                            >
                                                                                <RotateCcw className="h-3 w-3" /> Вернуть в очередь
                                                                            </button>
                                                                        )}
                                                                        {video.status === 'merged' && video.publish_status !== 'published' && (
                                                                            <button
                                                                                className="w-full text-left px-3 py-2 text-xs text-emerald-400 hover:bg-slate-800 flex items-center gap-2"
                                                                                onClick={() => changeVideoStatus(video.id, { publish_status: 'published' })}
                                                                            >
                                                                                <CheckCircle2 className="h-3 w-3" /> Отметить как опубликовано
                                                                            </button>
                                                                        )}
                                                                        {video.status !== 'merged' && (
                                                                            <button
                                                                                className="w-full text-left px-3 py-2 text-xs text-blue-400 hover:bg-slate-800 flex items-center gap-2"
                                                                                onClick={() => changeVideoStatus(video.id, { status: 'merged' })}
                                                                            >
                                                                                <CheckCircle2 className="h-3 w-3" /> Отметить как готово
                                                                            </button>
                                                                        )}
                                                                        {video.status !== 'failed' && (
                                                                            <button
                                                                                className="w-full text-left px-3 py-2 text-xs text-rose-400 hover:bg-slate-800 flex items-center gap-2"
                                                                                onClick={() => changeVideoStatus(video.id, { status: 'failed', publish_status: null })}
                                                                            >
                                                                                <AlertCircle className="h-3 w-3" /> Отметить как ошибка
                                                                            </button>
                                                                        )}
                                                                        {video.publish_status === 'failed' && (
                                                                            <button
                                                                                className="w-full text-left px-3 py-2 text-xs text-amber-400 hover:bg-slate-800 flex items-center gap-2"
                                                                                onClick={() => changeVideoStatus(video.id, { publish_status: null })}
                                                                            >
                                                                                <RotateCcw className="h-3 w-3" /> Сбросить статус публикации
                                                                            </button>
                                                                        )}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        </div>
                                                    </TableCell>
                                                </TableRow>
                                            );
                                        })}
                                </TableBody>
                            </Table>
                        </Card>
                    </TabsContent>

                    {/* ─── DESTINATIONS TAB ─── */}
                    <TabsContent value="destinations" className="space-y-4">
                        <div className="grid grid-cols-1 lg:grid-cols-[1fr_400px] gap-4">

                            {/* Left: Destinations List or Form */}
                            <div className="space-y-4">
                                {editingDest && (
                                    <Card className="bg-slate-900/30 border-slate-800 p-6 space-y-6">
                                        <div className="flex items-center justify-between mb-2">
                                            <h3 className="text-lg font-semibold">⚙️ Настройки автопубликации</h3>
                                            {editingDest.id && (
                                                <Badge className={editingDest.is_active ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-slate-500/10 text-slate-400 border-slate-500/20'}>
                                                    {editingDest.is_active ? 'Активно' : 'Выключено'}
                                                </Badge>
                                            )}
                                        </div>

                                        <div className="space-y-4">
                                            <div>
                                                <label className="text-xs text-slate-400 uppercase tracking-wider block mb-2">Upload-Post профили</label>
                                                {uploadPostProfiles.length > 0 ? (
                                                    <div className="grid grid-cols-2 gap-2">
                                                        {uploadPostProfiles.map((p: any) => {
                                                            const isSelected = (editingDest.uploadpost_profiles || []).includes(p.username);
                                                            const socials = p.social_accounts ? Object.keys(p.social_accounts).filter(k => p.social_accounts[k]).join(', ') : '';
                                                            return (
                                                                <button key={p.username} onClick={() => {
                                                                    const current = editingDest.uploadpost_profiles || [];
                                                                    setEditingDest({ ...editingDest, uploadpost_profiles: isSelected ? current.filter((x: string) => x !== p.username) : [...current, p.username] });
                                                                }} className={`p-3 rounded-lg border text-left transition-all ${isSelected ? 'border-blue-500/50 bg-blue-500/10' : 'border-slate-800 hover:border-slate-700'}`}>
                                                                    <span className={`text-sm font-medium ${isSelected ? 'text-blue-400' : 'text-slate-300'}`}>{p.username}</span>
                                                                    {socials && <p className="text-[10px] text-slate-500 mt-0.5">{socials}</p>}
                                                                </button>
                                                            );
                                                        })}
                                                    </div>
                                                ) : (
                                                    <div className="text-xs text-slate-500 py-2 px-3 bg-slate-950 border border-slate-800 rounded-md">
                                                        {envStatus?.env_key_configured ? 'Загрузка профилей...' : 'Настройте UPLOADPOST_API_KEY в .env'}
                                                    </div>
                                                )}
                                            </div>

                                            <div>
                                                <label className="text-xs text-slate-400 uppercase tracking-wider block mb-2">Платформы для публикации</label>
                                                <div className="grid grid-cols-3 gap-2">
                                                    {[
                                                        { id: 'tiktok', label: 'TikTok', emoji: '🎵' },
                                                        { id: 'youtube', label: 'YouTube', emoji: '▶️' },
                                                        { id: 'instagram', label: 'Instagram', emoji: '📸' },
                                                    ].map(p => {
                                                        const isSelected = (editingDest.platforms || []).includes(p.id);
                                                        return (
                                                            <button key={p.id} onClick={() => {
                                                                const plats = editingDest.platforms || [];
                                                                setEditingDest({ ...editingDest, platforms: isSelected ? plats.filter((x: string) => x !== p.id) : [...plats, p.id] });
                                                            }} className={`p-3 rounded-lg border flex flex-col items-center gap-2 transition-all ${isSelected ? 'border-blue-500/50 bg-blue-500/10 text-blue-400' : 'border-slate-800 text-slate-400'}`}>
                                                                <span className="text-xl">{p.emoji}</span>
                                                                <span className="text-xs font-medium">{p.label}</span>
                                                            </button>
                                                        );
                                                    })}
                                                </div>
                                            </div>

                                            {/* ─── Расписание ─── */}
                                            <div className="pt-3 border-t border-slate-800">
                                                <h5 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-3">📅 Расписание</h5>
                                                <div className="grid grid-cols-2 gap-4">
                                                    <div>
                                                        <label className="text-xs text-slate-400 block mb-1">Постов в день</label>
                                                        <Input type="number" min="1" max="20" value={editingDest.posts_per_day || 1} onChange={e => setEditingDest({ ...editingDest, posts_per_day: parseInt(e.target.value) })} className="bg-slate-950 border-slate-800" />
                                                    </div>
                                                    <div>
                                                        <label className="text-xs text-slate-400 block mb-1">Мин. пауза (мин)</label>
                                                        <Input type="number" min="1" value={editingDest.min_time_between_posts_minutes || 60} onChange={e => setEditingDest({ ...editingDest, min_time_between_posts_minutes: parseInt(e.target.value) })} className="bg-slate-950 border-slate-800" />
                                                    </div>
                                                    <div>
                                                        <label className="text-xs text-slate-400 block mb-1">Публикация с</label>
                                                        <Input type="time" value={editingDest.publish_window_start || '09:00'} onChange={e => setEditingDest({ ...editingDest, publish_window_start: e.target.value })} className="bg-slate-950 border-slate-800" />
                                                    </div>
                                                    <div>
                                                        <label className="text-xs text-slate-400 block mb-1">Публикация до</label>
                                                        <Input type="time" value={editingDest.publish_window_end || '22:00'} onChange={e => setEditingDest({ ...editingDest, publish_window_end: e.target.value })} className="bg-slate-950 border-slate-800" />
                                                    </div>
                                                </div>
                                            </div>

                                            {/* ─── Режим публикации ─── */}
                                            <div className="pt-3 border-t border-slate-800">
                                                <h5 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-3">🔧 Режим публикации</h5>
                                                <div className="grid grid-cols-2 gap-2">
                                                    {[
                                                        { id: 'auto', label: 'Авто-планировщик', emoji: '🤖', desc: 'По расписанию' },
                                                        { id: 'telegram', label: 'Telegram', emoji: '📩', desc: 'Ручная отправка' },
                                                    ].map(m => {
                                                        const isActive = (editingDest.publish_mode || 'auto') === m.id;
                                                        return (
                                                            <button key={m.id} onClick={() => setEditingDest({ ...editingDest, publish_mode: m.id })}
                                                                className={`p-3 rounded-lg border text-left transition-all ${isActive ? 'border-blue-500/50 bg-blue-500/10' : 'border-slate-800 hover:border-slate-700'}`}>
                                                                <div className="flex items-center gap-2 mb-1">
                                                                    <span>{m.emoji}</span>
                                                                    <span className={`text-sm font-medium ${isActive ? 'text-blue-400' : 'text-slate-300'}`}>{m.label}</span>
                                                                </div>
                                                                <p className="text-[10px] text-slate-500">{m.desc}</p>
                                                            </button>
                                                        );
                                                    })}
                                                </div>
                                                {(editingDest.publish_mode || 'auto') === 'telegram' && (
                                                    <div className="mt-3 space-y-3 p-3 bg-slate-950/50 rounded-lg border border-slate-800">
                                                        <div>
                                                            <label className="text-xs text-slate-400 block mb-1">Telegram Bot Token</label>
                                                            <Input value={editingDest.telegram_bot_token || ''} onChange={e => setEditingDest({ ...editingDest, telegram_bot_token: e.target.value })} placeholder="123456:ABC-DEF..." className="bg-slate-950 border-slate-800 font-mono text-xs" />
                                                        </div>
                                                        <div>
                                                            <label className="text-xs text-slate-400 block mb-1">Telegram Chat ID</label>
                                                            <Input value={editingDest.telegram_chat_id || ''} onChange={e => setEditingDest({ ...editingDest, telegram_chat_id: e.target.value })} placeholder="-100123456789" className="bg-slate-950 border-slate-800 font-mono text-xs" />
                                                        </div>
                                                    </div>
                                                )}
                                            </div>

                                            {/* ─── Приватность платформ ─── */}
                                            {(editingDest.platforms || []).length > 0 && (
                                                <div className="pt-3 border-t border-slate-800">
                                                    <h5 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-3">🔒 Настройки приватности</h5>
                                                    <div className="space-y-3">
                                                        {(editingDest.platforms || []).includes('tiktok') && (
                                                            <div>
                                                                <label className="text-xs text-slate-400 block mb-1">TikTok приватность</label>
                                                                <select value={editingDest.tiktok_privacy || 'PUBLIC_TO_EVERYONE'} onChange={e => setEditingDest({ ...editingDest, tiktok_privacy: e.target.value })} className="w-full text-sm bg-slate-950 border border-slate-800 rounded-md py-2 px-3 text-slate-300 focus:outline-none focus:ring-1 focus:ring-blue-500">
                                                                    <option value="PUBLIC_TO_EVERYONE">Публичный</option>
                                                                    <option value="MUTUAL_FOLLOW_FRIENDS">Друзья</option>
                                                                    <option value="SELF_ONLY">Только я</option>
                                                                </select>
                                                            </div>
                                                        )}
                                                        {(editingDest.platforms || []).includes('youtube') && (
                                                            <div className="grid grid-cols-2 gap-3">
                                                                <div>
                                                                    <label className="text-xs text-slate-400 block mb-1">YouTube приватность</label>
                                                                    <select value={editingDest.youtube_privacy || 'public'} onChange={e => setEditingDest({ ...editingDest, youtube_privacy: e.target.value })} className="w-full text-sm bg-slate-950 border border-slate-800 rounded-md py-2 px-3 text-slate-300 focus:outline-none focus:ring-1 focus:ring-blue-500">
                                                                        <option value="public">Публичный</option>
                                                                        <option value="unlisted">По ссылке</option>
                                                                        <option value="private">Приватный</option>
                                                                    </select>
                                                                </div>
                                                                <div>
                                                                    <label className="text-xs text-slate-400 block mb-1">YouTube категория</label>
                                                                    <select value={editingDest.youtube_category_id || '22'} onChange={e => setEditingDest({ ...editingDest, youtube_category_id: e.target.value })} className="w-full text-sm bg-slate-950 border border-slate-800 rounded-md py-2 px-3 text-slate-300 focus:outline-none focus:ring-1 focus:ring-blue-500">
                                                                        <option value="22">People &amp; Blogs</option>
                                                                        <option value="24">Entertainment</option>
                                                                        <option value="28">Science &amp; Technology</option>
                                                                        <option value="26">Howto &amp; Style</option>
                                                                        <option value="20">Gaming</option>
                                                                        <option value="10">Music</option>
                                                                    </select>
                                                                </div>
                                                            </div>
                                                        )}
                                                        {(editingDest.platforms || []).includes('instagram') && (
                                                            <div>
                                                                <label className="text-xs text-slate-400 block mb-1">Instagram тип</label>
                                                                <select value={editingDest.instagram_media_type || 'REELS'} onChange={e => setEditingDest({ ...editingDest, instagram_media_type: e.target.value })} className="w-full text-sm bg-slate-950 border border-slate-800 rounded-md py-2 px-3 text-slate-300 focus:outline-none focus:ring-1 focus:ring-blue-500">
                                                                    <option value="REELS">Reels</option>
                                                                    <option value="FEED">Feed</option>
                                                                    <option value="STORIES">Stories</option>
                                                                </select>
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            )}

                                            {/* ─── Footer: Active toggle + Save ─── */}
                                            <div className="flex items-center justify-between pt-4 border-t border-slate-800">
                                                <div className="flex items-center gap-3">
                                                    <button
                                                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${editingDest.is_active ? 'bg-emerald-500' : 'bg-slate-700'}`}
                                                        onClick={() => setEditingDest({ ...editingDest, is_active: !editingDest.is_active })}
                                                    >
                                                        <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${editingDest.is_active ? 'translate-x-6' : 'translate-x-1'}`} />
                                                    </button>
                                                    <span className="text-sm">{editingDest.is_active ? 'Автопубликация включена' : 'Автопубликация выключена'}</span>
                                                </div>
                                                <Button className="bg-blue-600 hover:bg-blue-500" onClick={() => saveDestination(editingDest)} disabled={destSaving}>
                                                    {destSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                                                    Сохранить
                                                </Button>
                                            </div>
                                        </div>
                                    </Card>
                                )}
                            </div>

                            {/* Right: Global Queue Status */}
                            <div className="space-y-4">
                                {envStatus && !envStatus.env_key_configured && (
                                    <div className="p-4 rounded-lg border border-amber-700/50 bg-amber-900/20">
                                        <p className="text-sm font-medium text-amber-300">⚠️ Ключ UploadPost не настроен</p>
                                        <p className="text-xs text-slate-500 mt-1">Добавьте UPLOADPOST_API_KEY в backend/.env</p>
                                    </div>
                                )}

                                <Card className="bg-slate-900/30 border-slate-800 p-5">
                                    <h4 className="font-semibold mb-3 flex items-center justify-between">
                                        Глобальная очередь
                                        <Badge className="bg-amber-500/10 text-amber-400 border-amber-500/20">{globalQueue?.queue_count || 0}</Badge>
                                    </h4>

                                    <p className="text-xs text-slate-500 mb-4">
                                        Все готовые видео попадают сюда. Каждый активный профиль берет из этой очереди 1 уникальное видео при публикации.
                                    </p>

                                    {/* Shuffle / Interleave Buttons */}
                                    {(globalQueue?.queue_count || 0) > 0 && (
                                        <div className="flex gap-2 mb-4">
                                            <Button
                                                variant="outline" size="sm"
                                                className="flex-1 border-purple-700 text-purple-400 hover:bg-purple-900/30 hover:text-purple-300 text-xs"
                                                onClick={async () => {
                                                    try {
                                                        await fetch(`${API}/api/videos/global-queue/shuffle`, { method: 'POST' });
                                                        fetchGlobalQueue();
                                                    } catch { alert('Ошибка соединения'); }
                                                }}
                                            >
                                                🔀 Перемешать
                                            </Button>
                                            <Button
                                                variant="outline" size="sm"
                                                className="flex-1 border-cyan-700 text-cyan-400 hover:bg-cyan-900/30 hover:text-cyan-300 text-xs"
                                                onClick={async () => {
                                                    try {
                                                        await fetch(`${API}/api/videos/global-queue/interleave`, { method: 'POST' });
                                                        fetchGlobalQueue();
                                                    } catch { alert('Ошибка соединения'); }
                                                }}
                                            >
                                                🔄 Вкрапить свои
                                            </Button>
                                        </div>
                                    )}

                                    {/* Queue List */}
                                    {(globalQueue?.queue_count || 0) > 0 ? (
                                        <div className="space-y-1.5 max-h-[300px] overflow-y-auto pr-1">
                                            {globalQueue.queue?.map((item: any, idx: number) => (
                                                <div key={item.id} className="flex items-center gap-3 p-2 rounded-lg bg-slate-950/30 border border-slate-800/50 text-xs">
                                                    <span className="text-slate-600 font-mono w-5 text-center shrink-0">{idx + 1}</span>
                                                    <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium ${item.source === 'upload' ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20' : 'bg-slate-500/10 text-slate-400 border border-slate-500/20'}`}>
                                                        {item.source === 'upload' ? '📤 Свой' : '🎵 TikTok'}
                                                    </span>
                                                    <span className="text-slate-300 truncate flex-1">{item.tiktok_id}</span>
                                                </div>
                                            ))}
                                        </div>
                                    ) : (
                                        <div className="text-center py-8 text-slate-600 text-sm border border-dashed border-slate-800 rounded-lg">
                                            Очередь пуста.<br />Парсер еще не подготовил видео.
                                        </div>
                                    )}
                                </Card>
                            </div>
                        </div>
                    </TabsContent>

                    <TabsContent value="design" className="space-y-4">
                        <Card className="bg-slate-900/30 border-slate-800 p-6">
                            <div className="mb-6">
                                <h3 className="text-xl font-semibold">Оформление видео</h3>
                                <p className="text-slate-400 text-sm mt-1">Настраивайте плашки и субтитры — изменения применяются к финальному видео.</p>
                            </div>

                            <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-8">
                                {/* ── LEFT: 9:16 Preview ── */}
                                <div className="space-y-3">
                                    <label className="text-xs font-medium text-slate-400 uppercase tracking-wider">Предпросмотр (9:16)</label>
                                    <div className="aspect-[9/16] bg-slate-950 rounded-xl border border-slate-800 relative overflow-hidden">
                                        {/* Background placeholder */}
                                        <div className="absolute inset-0 flex items-center justify-center">
                                            <span className="text-slate-700 text-xs italic">Фоновое видео</span>
                                        </div>

                                        {/* Overlay preview */}
                                        {(() => {
                                            const activeOverlay = overlays.find((o: any) => o.id === overlayDesign.selected_id);
                                            if (!activeOverlay) return null;
                                            const overlayUrl = activeOverlay.preview_url
                                                ? (activeOverlay.preview_url.startsWith('http') ? activeOverlay.preview_url : `${API}${activeOverlay.preview_url}`)
                                                : `${API}/${activeOverlay.file_path.replace(/^\/+/, '')}`;
                                            const isImage = activeOverlay.name.match(/\.(png|jpg|jpeg|gif|webp)$/i);
                                            const isVideo = activeOverlay.name.match(/\.(mp4|mov|webm)$/i);
                                            const scalePct = overlayDesign.scale;
                                            const yPos = overlayDesign.y_position;
                                            return (
                                                <div
                                                    className="absolute left-1/2 transition-all duration-300"
                                                    style={{
                                                        bottom: `${yPos}%`,
                                                        width: `${scalePct}%`,
                                                        transform: 'translateX(-50%)',
                                                    }}
                                                >
                                                    {isImage ? (
                                                        <img src={overlayUrl} alt="overlay" className="w-full h-auto" />
                                                    ) : isVideo ? (
                                                        <video src={overlayUrl} className="w-full h-auto" muted loop autoPlay />
                                                    ) : null}
                                                </div>
                                            );
                                        })()}

                                        {/* Subtitle preview */}
                                        {(() => {
                                            const activePreset = SUBTITLE_PRESETS.find(p => p.id === (subtitles.preset || 'classic'));
                                            if (!activePreset) return null;

                                            // Fallback to preset styles if custom isn't enabled
                                            const fontSize = subtitles.use_custom_styles ? subtitles.font_size : activePreset.fontSize;
                                            const primaryColor = subtitles.use_custom_styles ? subtitles.primary_color : activePreset.color;
                                            const outlineColor = subtitles.use_custom_styles ? subtitles.outline_color : activePreset.outline;
                                            const hasOutline = subtitles.use_custom_styles ? subtitles.has_outline : true; // Presets assume outline exists

                                            // The backend Margins are offset differently from CSS bottom percentage,
                                            // But for visual preview we do a rough map
                                            const bottomPercent = subtitles.use_custom_styles ? Math.min(90, Math.max(5, subtitles.vertical_position / 2)) : 10;
                                            const textShadow = hasOutline && !activePreset.bg ? `2px 2px 0 ${outlineColor}, -2px -2px 0 ${outlineColor}, 2px -2px 0 ${outlineColor}, -2px 2px 0 ${outlineColor}` : 'none';

                                            return (
                                                <div
                                                    className="absolute w-full px-4 text-center transition-all duration-300"
                                                    style={{
                                                        bottom: `${bottomPercent}%`,
                                                        fontSize: `${fontSize}px`,
                                                        color: primaryColor,
                                                        textShadow: textShadow,
                                                        fontWeight: 'bold',
                                                        visibility: subtitles.enabled ? 'visible' : 'hidden',
                                                        zIndex: 10,
                                                        ...(activePreset.bg ? { background: 'rgba(0,0,0,0.7)', padding: '4px 12px', borderRadius: '4px', width: 'auto', left: '50%', transform: 'translateX(-50%)' } : {}),
                                                    }}
                                                >
                                                    Пример субтитра
                                                </div>
                                            );
                                        })()}
                                    </div>
                                </div>

                                {/* ── RIGHT: Settings ── */}
                                <div className="space-y-6">
                                    {/* ─── Section: CTA Plates ─── */}
                                    <div className="space-y-4">
                                        <div className="flex justify-between items-center">
                                            <h4 className="text-sm font-bold text-slate-200 uppercase tracking-wider">Плашки / CTA</h4>
                                            <div className="relative">
                                                <Input type="file" id="overlay-upload" className="hidden" onChange={handleOverlayUpload} accept="image/*,video/*" />
                                                <Button
                                                    onClick={() => document.getElementById('overlay-upload')?.click()}
                                                    disabled={uploadingOverlay}
                                                    size="sm"
                                                    className="bg-blue-600 hover:bg-blue-500 text-xs"
                                                >
                                                    {uploadingOverlay ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Plus className="mr-1 h-3 w-3" />}
                                                    Загрузить
                                                </Button>
                                            </div>
                                        </div>

                                        {/* Horizontal overlay gallery */}
                                        {overlays.length === 0 ? (
                                            <div className="text-center py-6 text-slate-600 text-sm border border-dashed border-slate-800 rounded-lg">
                                                Нет плашек. Загрузите PNG/JPG или MP4.
                                            </div>
                                        ) : (
                                            <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-thin scrollbar-thumb-slate-800">
                                                {/* "No plate" option */}
                                                <div
                                                    className={`shrink-0 w-20 h-14 rounded-lg border-2 cursor-pointer flex items-center justify-center transition-all ${overlayDesign.selected_id === null ? 'border-blue-500 bg-blue-500/10' : 'border-slate-800 hover:border-slate-700 bg-slate-950'}`}
                                                    onClick={() => setOverlayDesign((p: any) => ({ ...p, selected_id: null }))}
                                                >
                                                    <X className="h-5 w-5 text-slate-500" />
                                                </div>
                                                {overlays.map((overlay: any) => {
                                                    const overlayUrl = overlay.preview_url
                                                        ? (overlay.preview_url.startsWith('http') ? overlay.preview_url : `${API}${overlay.preview_url}`)
                                                        : `${API}/${overlay.file_path.replace(/^\/+/, '')}`;
                                                    const isImage = overlay.name.match(/\.(png|jpg|jpeg|gif|webp)$/i);
                                                    const isVideo = overlay.name.match(/\.(mp4|mov|webm)$/i);
                                                    const isActive = overlayDesign.selected_id === overlay.id;
                                                    return (
                                                        <div
                                                            key={overlay.id}
                                                            className={`shrink-0 w-20 h-14 rounded-lg border-2 cursor-pointer overflow-hidden relative group transition-all ${isActive ? 'border-blue-500 shadow-lg shadow-blue-500/20' : 'border-slate-800 hover:border-slate-700'}`}
                                                            onClick={() => setOverlayDesign((p: any) => ({ ...p, selected_id: overlay.id }))}
                                                        >
                                                            {isImage ? (
                                                                <img src={overlayUrl} alt={overlay.name} className="w-full h-full object-cover" />
                                                            ) : isVideo ? (
                                                                <video src={overlayUrl} className="w-full h-full object-cover" muted loop autoPlay />
                                                            ) : (
                                                                <div className="w-full h-full bg-slate-900 flex items-center justify-center"><Video className="h-4 w-4 text-slate-700" /></div>
                                                            )}
                                                            {/* Delete on hover */}
                                                            <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                                                                <button
                                                                    className="text-rose-400 hover:text-rose-300 bg-black/50 rounded-full p-1"
                                                                    onClick={(e) => { e.stopPropagation(); deleteOverlay(overlay.id); if (isActive) setOverlayDesign((p: any) => ({ ...p, selected_id: null })); }}
                                                                >
                                                                    <Trash2 className="h-3 w-3" />
                                                                </button>
                                                            </div>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}

                                        {/* Overlay position controls — only when a plate is selected */}
                                        {overlayDesign.selected_id !== null && (
                                            <div className="grid grid-cols-2 gap-4 p-3 bg-slate-950/50 rounded-lg border border-slate-800">
                                                <div className="space-y-2">
                                                    <label className="text-xs font-medium text-slate-400 block">Положение (Y) {overlayDesign.y_position}%</label>
                                                    <input
                                                        type="range" min="0" max="80" step="1"
                                                        value={overlayDesign.y_position}
                                                        onChange={(e) => setOverlayDesign((p: any) => ({ ...p, y_position: parseInt(e.target.value) }))}
                                                        className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-500"
                                                    />
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-xs font-medium text-slate-400 block">Масштаб ({overlayDesign.scale}%)</label>
                                                    <input
                                                        type="range" min="30" max="150" step="5"
                                                        value={overlayDesign.scale}
                                                        onChange={(e) => setOverlayDesign((p: any) => ({ ...p, scale: parseInt(e.target.value) }))}
                                                        className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-500"
                                                    />
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    {/* ─── Divider ─── */}
                                    <div className="border-t border-slate-800" />

                                    {/* ─── Section: Subtitles ─── */}
                                    <div className="space-y-4">
                                        <div className="flex justify-between items-center">
                                            <h4 className="text-sm font-bold text-slate-200 uppercase tracking-wider">Субтитры</h4>
                                            <button
                                                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${subtitles.enabled ? 'bg-blue-600' : 'bg-slate-700'}`}
                                                onClick={() => setSubtitles((p: any) => ({ ...p, enabled: !p.enabled }))}
                                            >
                                                <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${subtitles.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
                                            </button>
                                        </div>

                                        {/* Preset cards */}
                                        <div className="grid grid-cols-1 gap-2">
                                            {SUBTITLE_PRESETS.map((preset) => {
                                                const isActive = (subtitles.preset || 'classic') === preset.id;
                                                return (
                                                    <div
                                                        key={preset.id}
                                                        className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all ${isActive
                                                            ? 'border-blue-500 bg-blue-500/10 shadow-lg shadow-blue-500/5'
                                                            : 'border-slate-800 hover:border-slate-700 bg-slate-950/30'
                                                            }`}
                                                        onClick={() => setSubtitles((p: any) => ({ ...p, preset: preset.id }))}
                                                    >
                                                        <div className="text-xl shrink-0">{preset.emoji}</div>
                                                        <div className="flex-1 min-w-0">
                                                            <p className={`text-sm font-bold ${isActive ? 'text-blue-400' : 'text-slate-300'}`}>{preset.label}</p>
                                                            <p className="text-xs text-slate-500 truncate">{preset.desc}</p>
                                                        </div>
                                                        {/* Mini visual preview */}
                                                        <div
                                                            className="shrink-0 px-2 py-1 rounded text-xs font-bold"
                                                            style={{
                                                                color: preset.color,
                                                                textShadow: preset.bg ? 'none' : `1px 1px 0 ${preset.outline}, -1px -1px 0 ${preset.outline}`,
                                                                background: preset.bg ? 'rgba(0,0,0,0.7)' : 'transparent',
                                                                fontSize: '11px',
                                                            }}
                                                        >
                                                            Aa
                                                        </div>
                                                        <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 ${isActive ? 'border-blue-500 bg-blue-500' : 'border-slate-700'}`}>
                                                            {isActive && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>

                                        {/* Advanced Custom Styling Toggle */}
                                        {subtitles.enabled && (
                                            <div className="mt-4 pt-3 border-t border-slate-800">
                                                <div className="flex items-center justify-between mb-3">
                                                    <h5 className="text-xs font-semibold text-slate-300">Кастомные стили (Advanced)</h5>
                                                    <button
                                                        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${subtitles.use_custom_styles ? 'bg-blue-600' : 'bg-slate-700'}`}
                                                        onClick={() => setSubtitles((p: any) => ({ ...p, use_custom_styles: !p.use_custom_styles }))}
                                                    >
                                                        <span className={`inline-block h-3 w-3 rounded-full bg-white shadow transition-transform ${subtitles.use_custom_styles ? 'translate-x-5' : 'translate-x-1'}`} />
                                                    </button>
                                                </div>

                                                {subtitles.use_custom_styles && (
                                                    <div className="space-y-4 p-3 bg-slate-950/50 rounded-lg border border-slate-800 animate-in fade-in slide-in-from-top-2 duration-200">
                                                        <div className="grid grid-cols-2 gap-4">
                                                            <div className="space-y-2">
                                                                <label className="text-xs text-slate-400 block">Размер шрифта ({subtitles.font_size})</label>
                                                                <input
                                                                    type="range" min="10" max="60" step="1"
                                                                    value={subtitles.font_size}
                                                                    onChange={(e) => setSubtitles((p: any) => ({ ...p, font_size: parseInt(e.target.value) }))}
                                                                    className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-500"
                                                                />
                                                            </div>
                                                            <div className="space-y-2">
                                                                <label className="text-xs text-slate-400 block">Позиция по высоте ({subtitles.vertical_position})</label>
                                                                <input
                                                                    type="range" min="0" max="400" step="5"
                                                                    value={subtitles.vertical_position}
                                                                    onChange={(e) => setSubtitles((p: any) => ({ ...p, vertical_position: parseInt(e.target.value) }))}
                                                                    className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-500"
                                                                />
                                                            </div>
                                                        </div>
                                                        <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
                                                            <label className="text-xs text-slate-400 block">Включить обводку текста</label>
                                                            <button
                                                                className={`relative inline-flex h-4 w-7 items-center rounded-full transition-colors ${subtitles.has_outline ? 'bg-blue-600' : 'bg-slate-700'}`}
                                                                onClick={() => setSubtitles((p: any) => ({ ...p, has_outline: !p.has_outline }))}
                                                            >
                                                                <span className={`inline-block h-2 w-2 rounded-full bg-white shadow transition-transform ${subtitles.has_outline ? 'translate-x-4' : 'translate-x-1'}`} />
                                                            </button>
                                                        </div>
                                                        <div className="grid grid-cols-2 gap-4">
                                                            <div className="space-y-1.5">
                                                                <label className="text-xs text-slate-400 block">Основной цвет</label>
                                                                <div className="flex gap-2 items-center">
                                                                    <input
                                                                        type="color"
                                                                        value={subtitles.primary_color}
                                                                        onChange={(e) => setSubtitles((p: any) => ({ ...p, primary_color: e.target.value }))}
                                                                        className="w-8 h-8 rounded shrink-0 bg-transparent border-0 cursor-pointer p-0"
                                                                    />
                                                                    <span className="text-xs text-slate-300 font-mono uppercase">{subtitles.primary_color}</span>
                                                                </div>
                                                            </div>
                                                            <div className={`space-y-1.5 transition-opacity ${subtitles.has_outline ? 'opacity-100' : 'opacity-30 pointer-events-none'}`}>
                                                                <label className="text-xs text-slate-400 block">Цвет контура</label>
                                                                <div className="flex gap-2 items-center">
                                                                    <input
                                                                        type="color"
                                                                        value={subtitles.outline_color}
                                                                        onChange={(e) => setSubtitles((p: any) => ({ ...p, outline_color: e.target.value }))}
                                                                        className="w-8 h-8 rounded shrink-0 bg-transparent border-0 cursor-pointer p-0"
                                                                    />
                                                                    <span className="text-xs text-slate-300 font-mono uppercase">{subtitles.outline_color}</span>
                                                                </div>
                                                            </div>
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </div>

                                    {/* Hint */}
                                    <p className="text-xs text-slate-600 italic pt-2 border-t border-slate-800">Все настройки применяются к финальному видео (FFmpeg).</p>
                                </div>
                            </div>
                        </Card>
                    </TabsContent>
                </Tabs>
            </div>

            {/* Video Player Modal */}
            {
                selectedVideo && (() => {
                    const videoUrl = getVideoUrl(selectedVideo);
                    return videoUrl ? (
                        <div
                            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
                            onClick={() => setSelectedVideo(null)}
                        >
                            <div
                                className="relative bg-slate-900 rounded-2xl overflow-hidden shadow-2xl border border-slate-700 max-w-sm w-full mx-4"
                                onClick={(e) => e.stopPropagation()}
                            >
                                <div className="flex items-center justify-between p-4 border-b border-slate-800">
                                    <div>
                                        <p className="text-sm font-semibold text-slate-200">Готовое видео</p>
                                        <p className="text-xs text-slate-500 truncate max-w-[220px]">{selectedVideo.tiktok_id}</p>
                                    </div>
                                    <button
                                        onClick={() => setSelectedVideo(null)}
                                        className="text-slate-400 hover:text-slate-200 transition-colors p-1 rounded-lg hover:bg-slate-800"
                                    >
                                        <X className="h-5 w-5" />
                                    </button>
                                </div>
                                <div className="bg-black flex items-center justify-center" style={{ maxHeight: '70vh' }}>
                                    <video
                                        src={videoUrl}
                                        controls
                                        autoPlay
                                        className="w-full"
                                        style={{ maxHeight: '70vh' }}
                                    />
                                </div>
                                <div className="p-4 flex gap-2">
                                    <a href={videoUrl} download className="flex-1">
                                        <Button variant="outline" className="w-full border-slate-700 text-slate-300 hover:bg-slate-800">
                                            <Download className="mr-2 h-4 w-4" /> Скачать
                                        </Button>
                                    </a>
                                </div>
                            </div>
                        </div>
                    ) : null;
                })()
            }

            {/* Upload Modal */}
            {uploadModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm px-4">
                    <Card className="w-full max-w-md bg-slate-900 border-slate-800 shadow-2xl">
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
                            <CardTitle className="text-xl font-bold">Загрузка видео</CardTitle>
                            <Button variant="ghost" size="icon" onClick={() => !uploadUploading && setUploadModal(false)} disabled={uploadUploading}>
                                <X className="h-4 w-4" />
                            </Button>
                        </CardHeader>
                        <CardContent className="space-y-6">
                            {/* File Selector — MULTI */}
                            <div
                                className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${uploadFiles.length > 0 ? 'border-emerald-500/50 bg-emerald-500/5' : 'border-slate-800 hover:border-slate-700 bg-slate-950/50'}`}
                                onClick={() => !uploadUploading && document.getElementById('video-upload')?.click()}
                                onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                                onDrop={(e) => {
                                    e.preventDefault(); e.stopPropagation();
                                    if (uploadUploading) return;
                                    const droppedFiles = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('video/'));
                                    if (droppedFiles.length) setUploadFiles(droppedFiles);
                                }}
                            >
                                <input
                                    type="file"
                                    id="video-upload"
                                    className="hidden"
                                    accept="video/mp4,video/x-m4v,video/*"
                                    multiple
                                    onChange={(e) => setUploadFiles(e.target.files ? Array.from(e.target.files) : [])}
                                />
                                {uploadFiles.length > 0 ? (
                                    <div className="space-y-2">
                                        <Video className="h-10 w-10 mx-auto text-emerald-500" />
                                        <p className="text-sm font-bold text-emerald-400">{uploadFiles.length} файл(ов) выбрано</p>
                                        <div className="max-h-24 overflow-y-auto space-y-0.5">
                                            {uploadFiles.map((f, i) => (
                                                <p key={i} className="text-xs text-slate-400 truncate max-w-xs mx-auto">{f.name} ({(f.size / 1024 / 1024).toFixed(1)} MB)</p>
                                            ))}
                                        </div>
                                        <Button variant="ghost" size="sm" className="text-xs text-slate-500 hover:text-slate-300" onClick={(e) => { e.stopPropagation(); setUploadFiles([]) }}>
                                            Сбросить
                                        </Button>
                                    </div>
                                ) : (
                                    <div className="space-y-2">
                                        <Upload className="h-10 w-10 mx-auto text-slate-600" />
                                        <p className="text-slate-400 text-sm">Нажмите или перетащите MP4 файлы</p>
                                        <p className="text-slate-600 text-xs">Можно выбрать несколько файлов</p>
                                    </div>
                                )}
                            </div>

                            {/* Processing Mode Selector */}
                            <div className="space-y-3">
                                <label className="text-xs font-semibold text-slate-500 uppercase">Режим обработки</label>
                                <div className="grid grid-cols-1 gap-2">
                                    {[
                                        { id: 'raw', label: 'Оригинал', desc: 'Публикация без изменений', icon: '📤' },
                                        { id: 'overlay', label: '+ Плашка', desc: 'Только наложение CTA-плашки', icon: '🎨' },
                                        { id: 'full', label: 'Полный пайплайн', desc: 'Анализ Gemini + Озвучка + Плашка', icon: '🤖' },
                                    ].map((m) => (
                                        <div
                                            key={m.id}
                                            className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all ${uploadMode === m.id ? 'border-blue-500 bg-blue-500/10 shadow-lg shadow-blue-500/5' : 'border-slate-800 hover:border-slate-700 bg-slate-950/30'}`}
                                            onClick={() => !uploadUploading && setUploadMode(m.id as any)}
                                        >
                                            <div className="text-2xl">{m.icon}</div>
                                            <div className="flex-1">
                                                <p className={`text-sm font-bold ${uploadMode === m.id ? 'text-blue-400' : 'text-slate-300'}`}>{m.label}</p>
                                                <p className="text-xs text-slate-500">{m.desc}</p>
                                            </div>
                                            <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${uploadMode === m.id ? 'border-blue-500 bg-blue-500' : 'border-slate-700'}`}>
                                                {uploadMode === m.id && <div className="w-2 h-2 rounded-full bg-white" />}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* Info */}
                            <div className="bg-blue-500/5 border border-blue-500/10 rounded-lg p-3">
                                <p className="text-xs text-slate-400 flex items-start gap-2">
                                    <span className="text-blue-400 shrink-0">ℹ️</span>
                                    {uploadFiles.length > 1
                                        ? <span>Все <span className="text-blue-300 font-bold">{uploadFiles.length}</span> видео будут обработаны по очереди (max 2 одновременно) и привязаны к профилю <span className="text-blue-300 font-bold">@{profile || 'default'}</span></span>
                                        : <span>Видео будет привязано к профилю <span className="text-blue-300 font-bold">@{profile || 'default'}</span></span>
                                    }
                                </p>
                            </div>

                            {/* Upload Progress */}
                            {uploadUploading && (
                                <div className="space-y-2">
                                    <div className="flex justify-between text-xs">
                                        <span className="text-slate-400">Загрузка {uploadFiles.length} файл(ов) на сервер...</span>
                                        <span className="text-blue-400 font-bold">{uploadProgress}%</span>
                                    </div>
                                    <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                                        <div className="h-full bg-blue-500 transition-all duration-300" style={{ width: `${uploadProgress}%` }} />
                                    </div>
                                </div>
                            )}

                            <Button
                                className="w-full h-12 bg-blue-600 hover:bg-blue-500 font-bold text-lg"
                                disabled={uploadFiles.length === 0 || uploadUploading}
                                onClick={handleUpload}
                            >
                                {uploadUploading ? (
                                    <>
                                        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                                        Загрузка...
                                    </>
                                ) : (
                                    uploadFiles.length > 1 ? `Загрузить ${uploadFiles.length} видео` : 'Запустить обработку'
                                )}
                            </Button>
                        </CardContent>
                    </Card>
                </div>
            )}
        </div >
    );
};

export default Dashboard;
