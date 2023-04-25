$(document).ready(function () {
    M.AutoInit();
    update_hidden_counts();
});

// Initialize datepickes with pt-br localization
function init_picker(selector, date) {
    let language = {
        "months": [
            "Janeiro",
            "Fevereiro",
            "Março",
            "Abril",
            "Maio",
            "Junho",
            "Julho",
            "Agosto",
            "Setembro",
            "Outubro",
            "Novembro",
            "Dezembro"
        ],
        "monthsShort": [
            "Jan",
            "Fev",
            "Mar",
            "Abr",
            "Mai",
            "Jun",
            "Jul",
            "Ago",
            "Set",
            "Out",
            "Nov",
            "Dez"
        ],
        "weekdays": ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sabado"],
        "weekdaysShort": ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sab"],
        "weekdaysAbbrev": ["D", "S", "T", "Q", "Q", "S", "S"],
        "cancel": "Cancelar",
        "clear": "Limpar"
    };
    let year_range = [2019, 2023];
    $(selector).datepicker({
        firstDay: true,
        format: 'dd/mm/yyyy',
        yearRange: year_range,
        defaultDate: datestr(date),
        setDefaultDate: true,
        autoClose: true,
        showClearBtn: true,
        i18n: language
    });
}

function update_url(param, value) {
    var base_url = window.location.href.split("?")[0];
    var param_txt = [param, value].join('=');

    if (window.location.href.split("?").length > 1) {
        var params = window.location.href.split("?")[1].split("&");
        var found = false;
        for (i in params) {
            if (params[i].split("=")[0] == param) {
                params[i] = param_txt;
                found = true;
            }
        }
        if (!found)
            params = params.concat([param_txt]);
    } else {
        var params = [param_txt];
    }
    var new_url = [base_url, params.join('&')].join('?');
    history.pushState(null, "", new_url);
}

//// Visualization control
// Toggle between short and full visualization for a text
function toggle_pannel(id) {
    $("#short_" + id).toggle();
    $("#full_" + id).toggle();
}

// Toggle visibility for a day
function toggle_day(id) {
    $(".toggle_inline_" + id).each(toggle_inline);
    $(".toggle_" + id).toggle();
}

// Auxiliary function to toggle visibility of round buttons
function toggle_inline() {
    if ($(this).is(':visible'))
        $(this).css('display', 'none');
    else
        $(this).css('display', 'inline-block');
}

// Toggle the visibility of hidden items
function toggle_hidden(show) {
    $(".hidden-entry").toggle();
    if (show) {
        $('#show-hidden').val("True");
        update_url('show-hidden', "True");
    } else {
        $('#show-hidden').val("False");
        update_url('show-hidden', "False");
    }
}

// Expands all visible entries
function expand_all() {
    $('.btn-expand').each(function () {
        if ($(this).is(':visible'))
            $(this).click();
    })
}

// Retract all visible entries
function retract_all() {
    $('.btn-retract').each(function () {
        if ($(this).is(':visible'))
            $(this).click();
    })
}

// Hide all dates above current
function hide_before(id, date) {
    var day = $("#" + id).prev()
    var prev = $("#" + id).prev()

    while (day.hasClass('day')) {
        console.log(day.attr('id'));
        prev = day.prev()
        day.remove()
        day = prev
    }
    $('#end-date').val(date);
    init_picker('#end-date', date);
    update_url('end-date', date);
}

// Hide all dates below current
function hide_after(id, date) {
    var day = $("#" + id).next()
    var next = $("#" + id).next()

    while (day.hasClass('day')) {
        console.log(day.attr('id'));
        next = day.next()
        day.remove()
        day = next
    }
    $('#start-date').val(date);
    init_picker('#start-date', date);
    update_url('start-date', date);
}

//// Visualization update functions
// Updates the hidden counts for each date
function update_hidden_counts() {
    $('.day').each(function () {
        var n = $(this).find('.hidden-entry').length
        if (n == 1)
            $(this).find('.hidden-count').text("(1 oculto)");
        else if (n > 1)
            $(this).find('.hidden-count').text("(" + n + " ocultos)");
        else
            $(this).find('.hidden-count').text("");
    })
}

//// Search form functions
// Clear a date field
function clear_date(id) {
    $("#" + id).val([]);
    //init_picker("#" + id, "");
    M.Datepicker.getInstance($("#" + id)).setDate();
}

// Creates a Date object from "DD/MM/YYYY" string
function datestr(datestr) {
    var splitDate = datestr.split("/");
    return new Date(splitDate[2], splitDate[1] - 1, splitDate[0]);
}

//// Backend communication functions
// Sends a command to the backend
function run_command(cmd, args) {
    var URL = "commands?cmd=" + cmd;

    for (i in args) {
        URL = URL + "&" + args[i];
    }

    fetch(URL)
        .then(response => response.json())
        .then((data) => {
            console.log(data);
            if (data.type == 'OK') {
                M.toast({ html: data.text, displayLength: 4000, classes: 'teal darken-3' });
                if (data.callback) {
                    console.log(data.callback)
                    eval(data.callback);
                }
            }
            else {
                M.toast({ html: "ERROR: " + data.text, displayLength: 20000, classes: 'red darken-4' });
                if (data.fail_callback) {
                    eval(data.fail_callback);
                }
            }
        })
}

// Calls the backend to hide an entry
function hide_one(text_id, patient_id) {
    run_command('hide-one', ['txt_id=' + text_id, 'patient_id=' + patient_id, 'callback=hide_text("' + text_id + '");'])
}

function show_warnning(message, action) {
    $("#warning-text").text(message);
    $('#warning-close').attr("onclick", action);
    M.Modal.getInstance($("#warning")).open();
}

// Calls the backend to hide all equal an entry
function hide_all(text, text_id, patient_id) {
    run_command('hide-all', ['text_id=' + text_id, 'patient_id=' + patient_id, 'text=' + text, 'callback=setTimeout(() => {window.location.reload();}, 1000);']);
}

// Calls the backend to unhide an entry
function unhide(text_id, patient_id) {
    run_command('show', ['txt_id=' + text_id, 'patient_id=' + patient_id, 'callback=unhide_text("' + text_id + '");']);
}

// Calls the backend to add a yes label to a patient
function add_patient_label(patient_id, label_id, label, value) {
    run_command('add-label', ['patient_id=' + patient_id, 'label=' + label, 'value=' + value, 'callback=mark_label("' + label_id + '", "' + value + '");']);
}

// Calls the backend to create a label
function create_label(label, patient_id) {
    run_command('new-label', ['label=' + label, 'patient_id=' + patient_id]);
    $("#new_label").val("");
}

//// Callback functions to hide, unhide entries, add elements, etc
// Change the state of a text to hidden
function hide_text(id) {
    if (!$('.btn-hide').is(':visible'))
        $("#text_" + id).hide();
    $("#text_" + id).addClass("hidden-entry");
    $("#full_" + id).removeClass("grey");
    $("#short_" + id).removeClass("grey");
    $("#full_" + id).removeClass("lighten-4");
    $("#short_" + id).removeClass("lighten-3");
    $("#full_" + id).addClass("red");
    $("#short_" + id).addClass("red");
    $("#full_" + id).addClass("lighten-5");
    $("#short_" + id).addClass("lighten-4");
    $("#full_" + id + " .btn-to-hide").css('display', 'none');
    $("#full_" + id + " .btn-to-show").css('display', 'inline-block');
    update_hidden_counts();
}

// Change the state of a text from hidden
function unhide_text(id) {
    $("#text_" + id).removeClass("hidden-entry");
    $("#full_" + id).removeClass("red");
    $("#short_" + id).removeClass("red");
    $("#full_" + id).removeClass("lighten-5");
    $("#short_" + id).removeClass("lighten-4");
    $("#full_" + id).addClass("grey");
    $("#short_" + id).addClass("grey");
    $("#full_" + id).addClass("lighten-4");
    $("#short_" + id).addClass("lighten-3");
    $("#full_" + id + " .btn-to-hide").css('display', 'inline-block');
    $("#full_" + id + " .btn-to-show").css('display', 'none');
    update_hidden_counts();
}

// Change a label selection to yes
function mark_label(label_id, value) {
    // Unselect all
    $("#no_sel_" + label_id).addClass("hidden");
    $("#no_" + label_id).removeClass("hidden");
    $("#yes_sel_" + label_id).addClass("hidden");
    $("#yes_" + label_id).removeClass("hidden");
    $("#idk_sel_" + label_id).addClass("hidden");
    $("#idk_" + label_id).removeClass("hidden");

    // Select back according to value
    if (value == "sim") {
        $("#yes_sel_" + label_id).removeClass("hidden");
        $("#yes_" + label_id).addClass("hidden");
    } else if (value == "nao") {
        $("#no_sel_" + label_id).removeClass("hidden");
        $("#no_" + label_id).addClass("hidden");
    } else if (value == "nao_sei") {
        $("#idk_sel_" + label_id).removeClass("hidden");
        $("#idk_" + label_id).addClass("hidden");
    }
}

// Add a label to the screen
function add_label(html) {
    $("#labels").append(html)
}

// Update hightlighted texts
function update_highlight() {
    $('.text-entry').unhighlight();
    var data = $('#highlights .chip').map(function () {
        var text = $(this).text()
        return text.substring(0, text.length - 5);
    }).get();
    $('.text-entry').highlight(data);
    update_url('highlight', '["' + data.join('","') + '"]')
}

// Initilize highlights and highlights chips
function init_highlight(data) {
    var data_obj = [];
    for (i in data) {
        data_obj.push({
            tag: data[i],
        })
    }
    let elems = document.querySelector('#highlights');
    let options = {
        onChipAdd: () => update_highlight(),
        onChipDelete: () => update_highlight(),
        placeholder: '+ Destaque',
        secondaryPlaceholder: '+ Destaque',
        data: data_obj,
    }
    let instances = M.Chips.init(elems, options);
    update_highlight();
}

// Calls the backend to remove an entry from hidden index
function remove_from_hidden(text_id) {
    run_command('remove-hidden', ['text_id=' + text_id])
}